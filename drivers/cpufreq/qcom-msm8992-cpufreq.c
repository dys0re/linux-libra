// SPDX-License-Identifier: GPL-2.0-only
/* MSM8992 cluster DVFS using the factory CPR open-loop calibration. */
#include <linux/clk.h>
#include <linux/debugfs.h>
#include <linux/delay.h>
#include <linux/cpufreq.h>
#include <linux/io.h>
#include <linux/math64.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/nvmem-consumer.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pm_domain.h>
#include <linux/pm_runtime.h>
#include <linux/regulator/consumer.h>
#include <linux/regmap.h>
#include <linux/thermal.h>
#include <linux/mfd/syscon.h>

#include "qcom-msm8992-cpr.h"

static bool enable;
module_param(enable, bool, 0600);
MODULE_PARM_DESC(enable, "Allow manual MSM8992 DVFS activation after sensor/clock validation");
static bool observe;
module_param(observe, bool, 0400);
MODULE_PARM_DESC(observe, "Read calibrated CPU voltage plans and SAW state without writes or cpufreq registration");
static bool saw_test;
module_param(saw_test, bool, 0400);
MODULE_PARM_DESC(saw_test, "Expose manual 1.000 to 1.005 V SAW test at the verified 600 MHz boot rates");
static bool clock_test;
module_param(clock_test, bool, 0400);
MODULE_PARM_DESC(clock_test, "Expose manual bootstrap CPU frequency selection at fixed 1.000 V and 300 MHz CCI");
static bool cci_test;
module_param(cci_test, bool, 0400);
MODULE_PARM_DESC(cci_test, "Expose manual 300/384 MHz CCI selection at the verified 600 MHz CPU boot rates");

struct msm8992_cpufreq {
	struct device *dev;
	struct clk *cpu[2], *cci;
	struct regulator *apc[2];
	struct msm8992_cpr_plan plan[2];
	struct cpufreq_frequency_table table[2][MSM8992_MAX_CORNERS + 1];
	struct mutex lock;
	struct regmap *saw[2];
};

static int msm8992_voltage_report_show(struct seq_file *seq, void *unused)
{
	struct msm8992_cpufreq *d = seq->private;
	/* Factory SAW ID/configuration, PMIC command slots and version only. */
	static const u32 offsets[] = {
		0x04, 0x08, 0x0c, 0x10, 0x14, 0x1c, 0x20,
		0x30, 0x34, 0x40, 0x44, 0x48, 0x4c, 0xfd0,
	};
	unsigned int c, i;
	int uv, ret;
	u32 value;

	seq_printf(seq, "A53=%lu A57=%lu CCI=%lu Hz\n",
		   clk_get_rate(d->cpu[0]), clk_get_rate(d->cpu[1]), clk_get_rate(d->cci));
	for (c = 0; c < 2; c++) {
		uv = regulator_get_voltage(d->apc[c]);
		if (uv < 0)
			return uv;
		seq_printf(seq, "APC%u PMIC_setpoint_uV=%d speedbin=%u revision=%u bank=%s\n",
			   c, uv, d->plan[c].speedbin, d->plan[c].revision,
			   d->plan[c].backup ? "backup" : "primary");
		for (i = 0; i < ARRAY_SIZE(offsets); i++) {
			ret = regmap_read(d->saw[c], offsets[i], &value);
			if (ret)
				return ret;
			seq_printf(seq, "SAW%u +0x%02x=0x%08x\n", c, offsets[i], value);
		}
		for (i = 0; i < d->plan[c].count; i++)
			seq_printf(seq, "APC%u corner%u %lu Hz %u uV\n", c, i + 1,
				   d->plan[c].hz[i], d->plan[c].uv[i]);
	}
	return 0;
}
DEFINE_SHOW_ATTRIBUTE(msm8992_voltage_report);

static int msm8992_saw_test_set(void *data, u64 cluster)
{
	struct msm8992_cpufreq *d = data;
	int ret, uv;

	if (cluster > 1)
		return -EINVAL;
	mutex_lock(&d->lock);
	/* Test only the verified boot point, with a 5 mV upward voltage step. */
	if (clk_get_rate(d->cpu[0]) != 600000000 ||
	    clk_get_rate(d->cpu[1]) != 600000000 || clk_get_rate(d->cci) != 300000000) {
		ret = -EBUSY;
		goto out;
	}
	uv = regulator_get_voltage(d->apc[cluster]);
	if (uv != 1000000) {
		ret = uv < 0 ? uv : -EBUSY;
		goto out;
	}
	dev_info(d->dev, "APC%llu SAW test: 600 MHz, requesting 1005000 uV\n", cluster);
	ret = regulator_set_voltage(d->apc[cluster], 1005000, 1005000);
	if (ret)
		goto out;
	usleep_range(1000, 2000);
	uv = regulator_get_voltage(d->apc[cluster]);
	dev_info(d->dev, "APC%llu SAW test: raised PMIC setpoint %d uV\n", cluster, uv);
	if (uv != 1005000) {
		ret = uv < 0 ? uv : -EIO;
		goto out;
	}
	ret = regulator_set_voltage(d->apc[cluster], 1000000, 1000000);
	if (ret)
		goto out;
	usleep_range(1000, 2000);
	uv = regulator_get_voltage(d->apc[cluster]);
	dev_info(d->dev, "APC%llu SAW test: restored PMIC setpoint %d uV\n", cluster, uv);
	ret = uv == 1000000 ? 0 : uv < 0 ? uv : -EIO;
out:
	mutex_unlock(&d->lock);
	return ret;
}
DEFINE_DEBUGFS_ATTRIBUTE(msm8992_saw_test_fops, NULL, msm8992_saw_test_set, "%llu\n");

static struct msm8992_cpufreq *msm8992_dvfs;

static unsigned int msm8992_voltage(struct msm8992_cpr_plan *plan, unsigned long hz)
{
	unsigned int i;

	for (i = 0; i < plan->count - 1 && plan->hz[i] < hz; i++)
		;
	return plan->uv[i];
}

static unsigned long msm8992_cci_target(unsigned long a53, unsigned long a57)
{
	const unsigned long cpu[] = { a53 / 1000, a57 / 1000 };
	const u32 *maps[] = { cci0_map, cci1_map };
	const unsigned int sizes[] = { ARRAY_SIZE(cci0_map), ARRAY_SIZE(cci1_map) };
	unsigned long hz = 134400000;
	unsigned int c, i;

	for (c = 0; c < 2; c++)
		for (i = 0; i < sizes[c]; i += 2)
			if (cpu[c] >= maps[c][i])
				hz = max(hz, maps[c][i + 1] * 1000UL);
	return hz;
}

static unsigned int msm8992_cci_voltage(struct msm8992_cpr_plan *plan, unsigned long hz)
{
	/* Factory CCI fmax-to-APC0 corner mapping; CCI shares the A53 rail. */
	static const unsigned long rates[] = {
		134400000, 300000000, 384000000, 556800000,
		600000000, 729600000, 787200000,
	};
	static const unsigned int corner[] = { 2, 4, 6, 6, 8, 8, 9 };
	unsigned int i;

	for (i = 0; i < ARRAY_SIZE(rates) - 1 && hz > rates[i]; i++)
		;
	return plan->uv[corner[i] - 1];
}

static int msm8992_set_voltage(struct msm8992_cpufreq *d, unsigned int c, unsigned int uv)
{
	return regulator_set_voltage(d->apc[c], uv, uv);
}

static void msm8992_recover_cci(struct msm8992_cpufreq *d, unsigned long old_rate)
{
	unsigned int i;
	int ret;

	if (clk_get_rate(d->cci) == old_rate)
		return;
	ret = clk_set_rate(d->cci, old_rate);
	if (!ret && clk_get_rate(d->cci) == old_rate)
		return;
	/* Keep the existing voltage votes while returning to the verified boot clocks. */
	for (i = 0; i < 2; i++) {
		ret = clk_set_rate(d->cpu[i], 600000000);
		if (ret)
			dev_err(d->dev, "APC%u auxiliary recovery failed: %d\n", i, ret);
	}
	ret = clk_set_rate(d->cci, 300000000);
	dev_warn(d->dev, "CCI recovery: actual %lu Hz, ret=%d\n", clk_get_rate(d->cci), ret);
}

static int msm8992_target(struct cpufreq_policy *policy, unsigned int index)
{
	struct msm8992_cpufreq *d = policy->driver_data;
	unsigned int c = policy->cpu < 4 ? 0 : 1;
	unsigned long hz = policy->freq_table[index].frequency * 1000UL;
	unsigned long request[2], old_cci, new_cci;
	unsigned long old_cpu;
	unsigned int uv[2], old_uv[2];
	int ret, i;

	guard(mutex)(&d->lock);
	request[0] = clk_get_rate(d->cpu[0]);
	request[1] = clk_get_rate(d->cpu[1]);
	old_cpu = request[c];
	request[c] = hz;
	new_cci = msm8992_cci_target(request[0], request[1]);
	old_cci = clk_get_rate(d->cci);
	for (i = 0; i < 2; i++) {
		ret = regulator_get_voltage(d->apc[i]);
		if (ret < 0)
			return ret;
		old_uv[i] = ret;
		/* Voltage floor covers the transient 600 MHz auxiliary clock. */
		uv[i] = max(msm8992_voltage(&d->plan[i], request[i]),
			    msm8992_voltage(&d->plan[i], 600000000));
	}
	uv[0] = max(uv[0], msm8992_cci_voltage(&d->plan[0], new_cci));
	/* Raise both supplies first. Keep the old vote until each clock settles. */
	for (i = 0; i < 2; i++) {
		ret = msm8992_set_voltage(d, i, max(uv[i], old_uv[i]));
		if (ret)
			return ret;
	}
	if (new_cci > old_cci) {
		ret = clk_set_rate(d->cci, new_cci);
		if (ret) {
			msm8992_recover_cci(d, old_cci);
			return ret;
		}
	}
	ret = clk_set_rate(d->cpu[c], hz);
	if (ret)
		return ret;
	if (new_cci < old_cci) {
		ret = clk_set_rate(d->cci, new_cci);
		if (ret) {
			msm8992_recover_cci(d, old_cci);
			/* Restore the CPU only after its former CCI rate is recovered. */
			if (clk_get_rate(d->cci) == old_cci)
				clk_set_rate(d->cpu[c], old_cpu);
			return ret;
		}
	}
	/* A failed down-vote only leaves excess voltage; the frequency succeeded. */
	for (i = 0; i < 2; i++) {
		ret = msm8992_set_voltage(d, i, uv[i]);
		if (ret)
			dev_warn_ratelimited(d->dev, "APC%u voltage down-vote failed: %d\n", i, ret);
	}
	return 0;
}

static int msm8992_policy_init(struct cpufreq_policy *policy)
{
	struct msm8992_cpufreq *d = msm8992_dvfs;
	unsigned int c = policy->cpu < 4 ? 0 : 1, cpu;

	cpufreq_generic_init(policy, d->table[c], 3000000);
	/* The generic helper marks all CPUs as shared; keep the two rails separate. */
	cpumask_clear(policy->cpus);
	for_each_possible_cpu(cpu)
		if ((cpu < 4 ? 0 : 1) == c)
			cpumask_set_cpu(cpu, policy->cpus);
	policy->driver_data = d;
	policy->clk = d->cpu[c];
	policy->dvfs_possible_from_any_cpu = true;
	return 0;
}

static struct freq_attr *msm8992_attrs[] = {
	&cpufreq_freq_attr_scaling_available_freqs,
	NULL,
};

static struct cpufreq_driver msm8992_driver = {
	.name = "msm8992-cpr",
	.flags = CPUFREQ_IS_COOLING_DEV | CPUFREQ_HAVE_GOVERNOR_PER_POLICY |
		 CPUFREQ_NEED_INITIAL_FREQ_CHECK,
	.verify = cpufreq_generic_frequency_table_verify,
	.target_index = msm8992_target,
	.get = cpufreq_generic_get,
	.init = msm8992_policy_init,
	.attr = msm8992_attrs,
};

/* Read only the factory-used rows; never sweep unrelated QFPROM regions. */
static int msm8992_read_cpr_fuses(struct device *dev, u8 *data)
{
	static const unsigned int rows[] = { 62, 137, 22, 138, 139, 140, 56, 57, 136 };
	unsigned int i;
	bool backup = false;

	for (i = 0; i < ARRAY_SIZE(rows); i++) {
		struct nvmem_cell *cell;
		char name[24];
		size_t len;
		u8 *value;

		if ((i >= 3 && i <= 5 && backup) || (i >= 6 && !backup))
			continue;
		snprintf(name, sizeof(name), "cpr-row%u", rows[i]);
		dev_info(dev, "CPR read: corrected row %u only\n", rows[i]);
		cell = devm_nvmem_cell_get(dev, name);
		if (IS_ERR(cell))
			return PTR_ERR(cell);
		value = nvmem_cell_read(cell, &len);
		if (IS_ERR(value))
			return PTR_ERR(value);
		if (len != 8) {
			kfree(value);
			return -EINVAL;
		}
		memcpy(data + rows[i] * 8, value, 8);
		kfree(value);
		if (!i)
			backup = msm8992_fuse_bits(data, 62, 48, 3) == 1;
	}
	return 0;
}

struct msm8992_clock_test {
	struct msm8992_cpufreq *d;
	unsigned int cluster;
};

static int msm8992_clock_test_set(void *data, u64 hz)
{
	struct msm8992_clock_test *test = data;
	struct msm8992_cpufreq *d = test->d;
	unsigned int c = test->cluster, i;
	unsigned long rates[2], old;
	unsigned long cci;
	long rounded;
	int ret;

	/* Bootstrap CPU PLL test; defer faster rates until CCI and thermal validation. */
	if (hz < 384000000 || hz > (c ? 600000000 : 672000000))
		return -ERANGE;
	guard(mutex)(&d->lock);
	for (i = 0; i < 2; i++) {
		ret = regulator_get_voltage(d->apc[i]);
		if (ret != 1000000)
			return ret < 0 ? ret : -EBUSY;
		rates[i] = clk_get_rate(d->cpu[i]);
	}
	cci = clk_get_rate(d->cci);
	if (cci != 300000000 && cci != 384000000)
		return -EBUSY;
	rounded = clk_round_rate(d->cpu[c], hz);
	if (rounded < 0)
		return rounded;
	if ((u64)rounded != hz)
		return -EINVAL;
	old = rates[c];
	rates[c] = hz;
	if (msm8992_cci_target(rates[0], rates[1]) > cci ||
	    max(msm8992_voltage(&d->plan[c], hz),
		msm8992_voltage(&d->plan[c], 600000000)) > 1000000)
		return -ERANGE;
	dev_info(d->dev, "APC%u CPU clock test: %lu -> %llu Hz at 1000000 uV, CCI %lu Hz\n",
		 c, old, hz, cci);
	ret = clk_set_rate(d->cpu[c], hz);
	dev_info(d->dev, "APC%u CPU clock test: actual %lu Hz, ret=%d\n",
		 c, clk_get_rate(d->cpu[c]), ret);
	if (ret)
		return ret;
	return clk_get_rate(d->cpu[c]) == hz ? 0 : -EIO;
}
DEFINE_DEBUGFS_ATTRIBUTE(msm8992_clock_test_fops, NULL, msm8992_clock_test_set, "%llu\n");

static int msm8992_cci_test_set(void *data, u64 hz)
{
	struct msm8992_cpufreq *d = data;
	unsigned long old, actual;
	int ret, restore, uv;

	if (hz != 300000000 && hz != 384000000)
		return -ERANGE;
	guard(mutex)(&d->lock);
	if (clk_get_rate(d->cpu[0]) != 600000000 || clk_get_rate(d->cpu[1]) != 600000000)
		return -EBUSY;
	uv = regulator_get_voltage(d->apc[0]);
	if (uv != 1000000)
		return uv < 0 ? uv : -EBUSY;
	if (msm8992_cci_voltage(&d->plan[0], hz) > 1000000)
		return -ERANGE;
	old = clk_get_rate(d->cci);
	if (old != 300000000 && old != 384000000 && !(old == 150000000 && hz == 300000000))
		return -EBUSY;
	dev_info(d->dev, "CCI clock test: %lu -> %llu Hz at APC0 1000000 uV\n", old, hz);
	ret = clk_set_rate(d->cci, hz);
	actual = clk_get_rate(d->cci);
	dev_info(d->dev, "CCI clock test: actual %lu Hz, ret=%d\n", actual, ret);
	if (!ret && actual == hz)
		return 0;
	if (!ret)
		ret = -EIO;
	/* Recover the boot auxiliary rate if the PLL/mux test fails. */
	if (actual != 300000000) {
		restore = clk_set_rate(d->cci, 300000000);
		dev_info(d->dev, "CCI clock test: restore actual %lu Hz, ret=%d\n",
			 clk_get_rate(d->cci), restore);
	}
	return ret;
}
DEFINE_DEBUGFS_ATTRIBUTE(msm8992_cci_test_fops, NULL, msm8992_cci_test_set, "%llu\n");

static int msm8992_thermal_ready(struct device *dev)
{
	static const char * const names[] = {
		"tsens7-thermal", "tsens9-thermal", "tsens10-thermal",
		"tsens13-thermal", "tsens14-thermal",
	};
	unsigned int i;
	int ret, temp;

	for (i = 0; i < ARRAY_SIZE(names); i++) {
		struct thermal_zone_device *zone = thermal_zone_get_zone_by_name(names[i]);

		if (IS_ERR(zone))
			return -EPROBE_DEFER;
		ret = thermal_zone_get_temp(zone, &temp);
		if (ret)
			return dev_err_probe(dev, -EPROBE_DEFER, "%s not ready: %d\n", names[i], ret);
	}
	return 0;
}

static int msm8992_cpufreq_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct msm8992_cpufreq *d;
	struct nvmem_cell *cell;
	u8 *data, *speed;
	size_t len;
	unsigned int c, i, n, bin;
	int ret;

	if (!enable) {
		dev_info(dev, "MSM8992 DVFS held for manual activation\n");
		return -ENODEV;
	}

	/* High frequency support requires the calibrated thermal zones first. */
	if (!observe) {
		ret = msm8992_thermal_ready(dev);
		if (ret)
			return ret;
	}
	d = devm_kzalloc(dev, sizeof(*d), GFP_KERNEL);
	if (!d)
		return -ENOMEM;
	d->dev = dev;
	mutex_init(&d->lock);
	if (observe)
		dev_info(dev, "voltage observation: reading corrected CPR calibration\n");
	data = kzalloc(0x500, GFP_KERNEL);
	if (!data)
		return -ENOMEM;
	ret = msm8992_read_cpr_fuses(dev, data);
	if (ret)
		goto free_data;
	cell = devm_nvmem_cell_get(dev, "speedbin");
	if (observe)
		dev_info(dev, "voltage observation: reading raw speed-bin row\n");
	if (IS_ERR(cell)) {
		ret = PTR_ERR(cell);
		goto free_data;
	}
	speed = nvmem_cell_read(cell, &len);
	if (IS_ERR(speed)) {
		ret = PTR_ERR(speed);
		goto free_data;
	}
	if (len != 8) {
		ret = -EINVAL;
		kfree(speed);
		goto free_data;
	}
	bin = (speed[7] & 3);
	kfree(speed);
	for (c = 0; c < 2; c++) {
		ret = msm8992_cpr_calculate(data, c, c ? msm8992_fuse_bits(data, 22, 0, 3) : bin, &d->plan[c]);
		if (ret)
			goto free_data;
	}
	kfree(data);
	for (c = 0; c < 2; c++) {
		d->cpu[c] = devm_clk_get(dev, c ? "a57" : "a53");
		if (IS_ERR(d->cpu[c]))
			return dev_err_probe(dev, PTR_ERR(d->cpu[c]), "cannot get CPU clock\n");
		d->apc[c] = devm_regulator_get(dev, c ? "apc1" : "apc0");
		if (IS_ERR(d->apc[c]))
			return dev_err_probe(dev, PTR_ERR(d->apc[c]), "cannot get APC supply\n");
		/* Skip the factory virtual 300 MHz corners, absent from CPU fmax tables. */
		for (i = 0, n = 0; i < d->plan[c].count; i++) {
			/* Preserve the verified auxiliary boot point on A57 as well. */
			if (c && d->plan[c].hz[i] == 633600000)
				d->table[c][n++].frequency = 600000;
			if (d->plan[c].hz[i] >= 384000000)
				d->table[c][n++].frequency = d->plan[c].hz[i] / 1000;
		}
		d->table[c][n].frequency = CPUFREQ_TABLE_END;
		for (i = 0; i < d->plan[c].count; i++)
			dev_info(dev, "APC%u factory OPP: %lu Hz %u uV\n", c,
				 d->plan[c].hz[i], d->plan[c].uv[i]);
		dev_info(dev, "APC%u: speedbin %u, CPR revision %u, %s open-loop calibration\n",
			 c, d->plan[c].speedbin, d->plan[c].revision,
			 d->plan[c].backup ? "backup" : "primary");
	}
	d->cci = devm_clk_get(dev, "cci");
	if (IS_ERR(d->cci))
		return dev_err_probe(dev, PTR_ERR(d->cci), "cannot get CCI clock\n");
	if (observe) {
		struct msm8992_clock_test *test = NULL;

		if (clock_test) {
			test = devm_kcalloc(dev, 2, sizeof(*test), GFP_KERNEL);
			if (!test)
				return -ENOMEM;
		}
		for (c = 0; c < 2; c++) {
			struct device_node *node = of_parse_phandle(dev->of_node, "qcom,saw-regs", c);

			dev_info(dev, "voltage observation: mapping APC%u SAW controller\n", c);
			if (!node)
				return -EINVAL;
			d->saw[c] = syscon_node_to_regmap(node);
			of_node_put(node);
			if (IS_ERR(d->saw[c]))
				return PTR_ERR(d->saw[c]);
		}
		debugfs_create_file("libra_voltage_observe", 0400, NULL, d,
				    &msm8992_voltage_report_fops);
		if (saw_test)
			debugfs_create_file("libra_saw_voltage_test", 0200, NULL, d,
					    &msm8992_saw_test_fops);
		if (clock_test)
			for (c = 0; c < 2; c++) {
				test[c].d = d;
				test[c].cluster = c;
				debugfs_create_file(c ? "libra_a57_clock_test" : "libra_a53_clock_test",
						    0200, NULL, &test[c], &msm8992_clock_test_fops);
			}
		if (cci_test)
			debugfs_create_file("libra_cci_clock_test", 0200, NULL, d,
					    &msm8992_cci_test_fops);
		dev_info(dev, "MSM8992 voltage observation ready; no voltage/clock/CPR writes\n");
		return 0;
	}
	/* Factory MX corner 7 is encoded as 6; preserve boot-time BIMC/NoC votes. */
	ret = dev_pm_genpd_set_performance_state(dev, 6);
	if (ret)
		return ret;
	pm_runtime_enable(dev);
	ret = pm_runtime_resume_and_get(dev);
	if (ret < 0)
		goto clear_pm;
	/* Use calibrated open-loop voltages, with autonomous CPR loops disabled. */
	for (c = 0; c < 2; c++) {
		void __iomem *base = devm_platform_ioremap_resource(pdev, c);

		if (IS_ERR(base)) {
			ret = PTR_ERR(base);
			goto put_pm;
		}
		writel(0, base + 0x100);
		writel(readl(base + 0x90) & ~BIT(0), base + 0x90);
		readl(base + 0x90);
	}
	msm8992_dvfs = d;
	ret = cpufreq_register_driver(&msm8992_driver);
	if (!ret) {
		dev_info(dev, "MSM8992 cpufreq ready: calibrated factory plans, CPU cooling and schedutil\n");
		return 0;
	}
	msm8992_dvfs = NULL;
put_pm:
	pm_runtime_put_sync(dev);
clear_pm:
	pm_runtime_disable(dev);
	dev_pm_genpd_set_performance_state(dev, 0);
	return ret;
free_data:
	kfree(data);
	return ret;
}

static const struct of_device_id msm8992_cpufreq_match[] = {
	{ .compatible = "qcom,msm8992-cpufreq" },
	{ }
};

static struct platform_driver msm8992_cpufreq_platform_driver = {
	.probe = msm8992_cpufreq_probe,
	.driver = {
		.name = "msm8992-cpufreq",
		.of_match_table = msm8992_cpufreq_match,
		.suppress_bind_attrs = true,
	},
};
builtin_platform_driver(msm8992_cpufreq_platform_driver);
