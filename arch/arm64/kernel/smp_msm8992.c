// SPDX-License-Identifier: GPL-2.0-only
/*
 * MSM8992 cold CPU boot, adapted from Qualcomm cpu_ops.c/cpu_pwr_ctl.c.
 * Copyright (c) 2014-2015, The Linux Foundation. All rights reserved.
 */

#define pr_fmt(fmt) "msm8992-smp: " fmt

#include <linux/delay.h>
#include <linux/firmware/qcom/qcom_scm.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/of.h>
#include <linux/of_address.h>
#include <linux/smp.h>

#include <asm/cacheflush.h>
#include <asm/cpu_ops.h>
#include <asm/cputype.h>
#include <asm/smp_plat.h>

#define CPU_PWR_CTL	0x04
#define CPU_PWR_GATE_CTL	0x14
#define L2_PWR_CTL	0x14
#define L2_PWR_OVERRIDE	0x0c
#define L2_POWERED	(BIT(9) | BIT(28))

extern void secondary_holding_pen(void);
extern volatile unsigned long secondary_holding_pen_release;

struct msm8992_cpu_power {
	void __iomem *acc;
	void __iomem *ldo;
	void __iomem *l2;
	void __iomem *saw;
	void __iomem *q2s;
	phys_addr_t l2_kick;
	u32 retention;
	bool cold_boot_done;
};

static struct msm8992_cpu_power cpu_power[NR_CPUS];

static int __init msm8992_cpu_init(unsigned int cpu)
{
	return 0;
}

static void msm8992_configure_ldo(struct msm8992_cpu_power *p)
{
	u32 val;

	val = readl(p->ldo + 0x28);
	writel((val & ~GENMASK(7, 0)) | 0x12, p->ldo + 0x28);
	val = readl(p->ldo + 0x0c);
	writel((val & ~GENMASK(15, 0)) | 0xf8c2, p->ldo + 0x0c);
	val = readl(p->ldo + 0x10);
	writel((val & ~(GENMASK(23, 16) | GENMASK(7, 0))) | 0x4a0060,
	       p->ldo + 0x10);
	val = readl(p->ldo + 0x04);
	val &= ~(BIT(16) | GENMASK(14, 8));
	writel(val | (p->retention << 8), p->ldo + 0x04);
	writel(0, p->ldo);
	writel(1, p->ldo);
	readl(p->ldo);
	udelay(1);
	writel(0, p->ldo);
	readl(p->ldo);
}

static int __init msm8992_cpu_prepare(unsigned int cpu)
{
	struct msm8992_cpu_power *p = &cpu_power[cpu];
	struct device_node *np, *acc, *l2;
	struct resource res;
	static bool boot_address_set;
	u32 cluster = MPIDR_AFFINITY_LEVEL(cpu_logical_map(cpu), 1);
	int ret;

	if (cluster > 1)
		return -EINVAL;

	if (!boot_address_set) {
		ret = qcom_scm_msm8992_set_boot_addr(__pa_symbol(secondary_holding_pen));
		if (ret) {
			pr_err("cannot register AArch64 boot address: %d\n", ret);
			return ret;
		}
		boot_address_set = true;
	}

	np = of_get_cpu_node(cpu, NULL);
	if (!np)
		return -ENODEV;
	acc = of_parse_phandle(np, "qcom,acc", 0);
	l2 = of_parse_phandle(np, "qcom,l2-power", 0);
	ret = of_property_read_u32(np, "qcom,ldo-retention-voltage", &p->retention);
	if (!acc || !l2 || ret || p->retention > 0x7f) {
		ret = -EINVAL;
		goto put_nodes;
	}
	ret = of_address_to_resource(l2, 6, &res);
	if (ret)
		goto put_nodes;
	p->l2_kick = res.start;
	p->ldo = of_iomap(acc, 0);
	p->acc = of_iomap(acc, 1);
	p->l2 = of_iomap(l2, cluster);
	p->saw = of_iomap(l2, 2 + cluster);
	p->q2s = of_iomap(l2, 4 + cluster);
	if (!p->ldo || !p->acc || !p->l2 || !p->saw || !p->q2s) {
		iounmap(p->ldo);
		iounmap(p->acc);
		iounmap(p->l2);
		iounmap(p->saw);
		iounmap(p->q2s);
		ret = -ENOMEM;
		goto put_nodes;
	}
	/* Downstream starts both clusters on the 600 MHz GPLL0 auxiliary path. */
	writel(0x6, p->l2 + 0x54);
	readl(p->l2 + 0x54);
	udelay(5);
	ret = 0;
put_nodes:
	of_node_put(acc);
	of_node_put(l2);
	of_node_put(np);
	return ret;
}

static int msm8992_power_on_l2(struct msm8992_cpu_power *p)
{
	static const struct {
		u32 value;
		u8 delay;
	} sequence[] = {
		{ 0x00029716, 8 }, { 0x00023716, 0 },
		{ 0x0002371e, 8 }, { 0x0002371c, 4 },
		{ 0x0002361c, 2 }, { 0x00022218, 4 },
		{ 0x10022218, 0 },
	};
	u32 val;
	int ret, i;

	if ((readl(p->l2 + L2_PWR_CTL) & L2_POWERED) == L2_POWERED) {
		if (!(readl(p->saw + 0x0c) & GENMASK(31, 16)))
			return 0;
		ret = qcom_scm_io_readl(p->l2_kick, &val);
		if (ret)
			return ret;
		ret = qcom_scm_io_writel(p->l2_kick, val | BIT(0));
		if (ret)
			return ret;
		return readl_poll_timeout_atomic(p->saw + 0x0c, val,
						!(val & GENMASK(31, 16)), 10, 2000);
	}

	/* A57 rail startup, including the downstream Q2S and SAW sequence. */
	writel(0x2, p->q2s);
	writel(0xb8, p->saw + 0x1c);
	udelay(2000);
	writel(0x30080, p->saw + 0x1c);
	udelay(2000);
	writel(0, p->l2 + 0x284);
	writel(0x00400000, p->l2 + L2_PWR_OVERRIDE);
	for (i = 0; i < ARRAY_SIZE(sequence); i++) {
		writel(sequence[i].value, p->l2 + L2_PWR_CTL);
		if (sequence[i].delay)
			udelay(sequence[i].delay);
	}
	writel(0, p->l2 + L2_PWR_OVERRIDE);
	readl(p->l2 + L2_PWR_OVERRIDE);
	return 0;
}

static int msm8992_cpu_boot(unsigned int cpu)
{
	struct msm8992_cpu_power *p = &cpu_power[cpu];
	u32 val;
	int ret;

	if (!p->cold_boot_done) {
		ret = msm8992_power_on_l2(p);
		if (ret)
			return ret;
		writel(0x01, p->acc + CPU_PWR_GATE_CTL);
		udelay(1);
		writel(0x03, p->acc + CPU_PWR_GATE_CTL);
		udelay(1);
		writel(0x79, p->acc + CPU_PWR_CTL);
		udelay(2);
		writel(0x7d, p->acc + CPU_PWR_CTL);
		udelay(2);
		writel(0x3d, p->acc + CPU_PWR_CTL);
		writel(0x3c, p->acc + CPU_PWR_CTL);
		udelay(1);
		writel(0x0c, p->acc + CPU_PWR_CTL);
		writel(0x8c, p->acc + CPU_PWR_CTL);
		readl(p->acc + CPU_PWR_CTL);
		ret = qcom_scm_io_readl(p->l2_kick, &val);
		if (ret)
			return ret;
		ret = qcom_scm_io_writel(p->l2_kick, val & ~BIT(0));
		if (ret)
			return ret;
		msm8992_configure_ldo(p);
		p->cold_boot_done = true;
	}

	WRITE_ONCE(secondary_holding_pen_release, cpu_logical_map(cpu));
	dcache_clean_inval_poc((unsigned long)&secondary_holding_pen_release,
			      (unsigned long)&secondary_holding_pen_release +
			      sizeof(secondary_holding_pen_release));
	sev();
	return 0;
}

#ifdef CONFIG_HOTPLUG_CPU
static bool msm8992_cpu_can_disable(unsigned int cpu)
{
	return false;
}
#endif

const struct cpu_operations msm8992_cpu_ops = {
	.name = "qcom,8994-arm-cortex-acc",
	.cpu_init = msm8992_cpu_init,
	.cpu_prepare = msm8992_cpu_prepare,
	.cpu_boot = msm8992_cpu_boot,
#ifdef CONFIG_HOTPLUG_CPU
	.cpu_can_disable = msm8992_cpu_can_disable,
#endif
};
