// SPDX-License-Identifier: GPL-2.0-only
/* MSM8992 auxiliary CPU clock, selected by the legacy CPU boot protocol. */

#include <linux/clk.h>
#include <linux/clk-provider.h>
#include <linux/delay.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/math64.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pm_domain.h>
#include <linux/firmware/qcom/qcom_scm.h>
#include <linux/pm_runtime.h>

static bool clusters_probe;
module_param(clusters_probe, bool, 0600);
MODULE_PARM_DESC(clusters_probe, "Allow manual MSM8992 cluster/CCI clock probe during bring-up");
static bool clocks_observe;
module_param(clocks_observe, bool, 0400);
MODULE_PARM_DESC(clocks_observe, "Register read-only cluster/CCI clocks without supply votes or rate changes");
static bool clocks_test;
module_param(clocks_test, bool, 0400);
MODULE_PARM_DESC(clocks_test, "Allow manually requested CPU clock changes in observation mode; CCI stays read-only");
static bool cci_test;
module_param(cci_test, bool, 0400);
MODULE_PARM_DESC(cci_test, "Allow manually requested CCI clock changes in observation mode");

#define CPU_MUX		0x54
#define LF_SEL		GENMASK(2, 1)
#define HF_SEL		GENMASK(4, 3)
#define PLL_MODE		0x00
#define PLL_L		0x04
#define PLL_ALPHA	0x08
#define PLL_USER		0x10
#define PLL_CONFIG	0x14
#define PLL_TEST_LO	0x20
#define PLL_TEST_HI	0x24

struct msm8992_cluster_clk {
	struct clk_hw hw;
	void __iomem *mux;
	void __iomem *pll;
	unsigned long xo_rate;
	unsigned int cluster;
};

#define to_cluster_clk(hw) container_of(hw, struct msm8992_cluster_clk, hw)

static void msm8992_mux_write(struct msm8992_cluster_clk *c, u32 mask, u32 val)
{
	u32 mux = readl(c->mux + CPU_MUX);

	writel((mux & ~mask) | val, c->mux + CPU_MUX);
	readl(c->mux + CPU_MUX);
	/* Qualcomm requires 5 us after each mux switch. */
	udelay(5);
}

static void msm8992_select_aux(struct msm8992_cluster_clk *c)
{
	/* Set the LF source before switching HF away from either CPU PLL. */
	msm8992_mux_write(c, LF_SEL, 3 << 1);
	msm8992_mux_write(c, HF_SEL, 0);
}

static unsigned long msm8992_cluster_recalc_rate(struct clk_hw *hw,
					       unsigned long parent_rate)
{
	struct msm8992_cluster_clk *c = to_cluster_clk(hw);
	u32 mux = readl(c->mux + CPU_MUX);
	u32 hf = (mux & HF_SEL) >> 3, lf = (mux & LF_SEL) >> 1;
	void __iomem *pll = c->pll;
	unsigned long rate;
	u32 div;

	if (!hf && lf == 3)
		return parent_rate;
	if (!hf && !lf)
		return c->xo_rate;
	if (hf == 1 || (!hf && lf == 1))
		pll += 0x40;
	rate = readl(pll + PLL_L) * c->xo_rate;
	if (hf)
		return rate;
	div = (readl(pll + PLL_USER) >> 8) & 3;
	return rate / (div + 1);
}

static const unsigned long msm8992_a53_rates[] = {
	384000000, 460800000, 600000000, 672000000, 787200000,
	864000000, 960000000, 1248000000, 1440000000,
};
static const unsigned long msm8992_a57_rates[] = {
	384000000, 480000000, 600000000, 633600000, 768000000, 864000000,
	960000000, 1248000000, 1344000000, 1440000000, 1536000000,
	1632000000, 1689600000, 1824000000,
};

static long msm8992_cluster_round_rate(struct clk_hw *hw, unsigned long rate,
				      unsigned long *parent_rate)
{
	struct msm8992_cluster_clk *c = to_cluster_clk(hw);
	const unsigned long *rates = c->cluster ? msm8992_a57_rates : msm8992_a53_rates;
	unsigned int count = c->cluster ? ARRAY_SIZE(msm8992_a57_rates) : ARRAY_SIZE(msm8992_a53_rates);
	unsigned int i;

	for (i = 0; i < count - 1 && rate > rates[i]; i++)
		;
	return rates[i];
}

static int msm8992_cluster_set_rate(struct clk_hw *hw, unsigned long rate,
				    unsigned long parent_rate)
{
	struct msm8992_cluster_clk *c = to_cluster_clk(hw);
	u32 mode, user, lock, div;
	unsigned long parent = parent_rate;
	int ret;

	if (rate != (unsigned long)msm8992_cluster_round_rate(hw, rate, &parent))
		return -EINVAL;
	/* Cpufreq supplies the safe auxiliary voltage before entering this callback. */
	msm8992_select_aux(c);
	mode = readl(c->pll + PLL_MODE) & ~(BIT(24) | GENMASK(2, 0));
	writel(mode, c->pll + PLL_MODE);
	readl(c->pll + PLL_MODE);
	if (rate == 600000000)
		return 0;

	/* Main /4 or /2 below the VCO minimum, early output at higher rates. */
	div = rate < 1209600000 ? (rate * 2 < 1209600000 ? 4 : 2) : 1;
	writel(rate * div / c->xo_rate, c->pll + PLL_L);
	writel(0, c->pll + PLL_ALPHA);
	user = readl(c->pll + PLL_USER);
	user &= ~(BIT(24) | BIT(12) | GENMASK(9, 8));
	user |= BIT(0) | BIT(3) | ((div == 4 ? 3 : 1) << 8);
	writel(user, c->pll + PLL_USER);
	/* MSM8992/v2 factory configuration, not MSM8994/v1 values. */
	writel(0x004d6968, c->pll + PLL_CONFIG);
	writel(0x80000000, c->pll + PLL_TEST_LO);
	writel(1, c->pll + PLL_TEST_HI);
	mode |= BIT(3);
	writel(mode, c->pll + PLL_MODE);
	writel(0x800000c0, c->pll + PLL_TEST_LO);
	readl(c->pll + PLL_TEST_LO);
	mode |= BIT(1);
	writel(mode, c->pll + PLL_MODE);
	readl(c->pll + PLL_MODE);
	udelay(10);
	mode |= BIT(2);
	writel(mode, c->pll + PLL_MODE);
	readl(c->pll + PLL_MODE);
	/* Factory delay avoids early transient lock indications. */
	udelay(200);
	ret = readl_poll_timeout_atomic(c->pll + PLL_MODE, lock,
				       lock & BIT(31), 1, 1000);
	if (ret)
		goto disable_pll;
	udelay(1);
	if (!(readl(c->pll + PLL_MODE) & BIT(31))) {
		ret = -ETIMEDOUT;
		goto disable_pll;
	}
	writel(mode | BIT(0), c->pll + PLL_MODE);
	readl(c->pll + PLL_MODE);
	if (div == 1)
		msm8992_mux_write(c, HF_SEL, 3 << 3);
	else
		msm8992_mux_write(c, LF_SEL, 2 << 1);
	return 0;

disable_pll:
	/* CPUs still run on GPLL0; report failure instead of selecting an unlocked PLL. */
	writel(mode & ~GENMASK(2, 0), c->pll + PLL_MODE);
	return ret;
}

static const struct clk_ops msm8992_cluster_ops = {
	.recalc_rate = msm8992_cluster_recalc_rate,
	.round_rate = msm8992_cluster_round_rate,
	.set_rate = msm8992_cluster_set_rate,
};

static const struct clk_ops msm8992_cluster_observe_ops = {
	.recalc_rate = msm8992_cluster_recalc_rate,
};

struct msm8992_cci_clk {
	struct clk_hw hw;
	void __iomem *pll;
	phys_addr_t mux;
};

#define to_cci_clk(hw) container_of(hw, struct msm8992_cci_clk, hw)

static const unsigned long msm8992_cci_rates[] = {
	134400000, 150000000, 300000000, 384000000, 556800000,
	600000000, 729600000, 787200000,
};

static int msm8992_cci_mux(struct msm8992_cci_clk *c, u32 mask, u32 value)
{
	u32 reg;
	int ret;

	ret = qcom_scm_io_readl(c->mux + 0x11c, &reg);
	if (ret)
		return ret;
	ret = qcom_scm_io_writel(c->mux + 0x11c, (reg & ~mask) | value);
	if (!ret)
		udelay(5);
	return ret;
}

static unsigned long msm8992_cci_recalc_rate(struct clk_hw *hw,
					   unsigned long parent_rate)
{
	struct msm8992_cci_clk *c = to_cci_clk(hw);
	u32 mux, hf, div;
	unsigned long rate;

	if (qcom_scm_io_readl(c->mux + 0x11c, &mux))
		return 0;
	hf = (mux >> 3) & 3;
	div = ((mux >> 5) & 3) + 1;
	if (hf == 1)
		rate = (mux & BIT(1)) ? parent_rate : 19200000;
	else {
		rate = readl(c->pll + PLL_L) * 19200000UL;
		if (readl(c->pll + PLL_USER) & BIT(24)) {
			u64 alpha = ((u64)(readl(c->pll + 0x0c) & 0xff) << 32) |
				    readl(c->pll + PLL_ALPHA);

			rate += mul_u64_u32_shr(alpha, 19200000, 40);
		}
		if (hf == 2)
			rate /= 2;
	}
	return rate / div;
}

static long msm8992_cci_round_rate(struct clk_hw *hw, unsigned long rate,
				  unsigned long *parent_rate)
{
	unsigned int i;

	for (i = 0; i < ARRAY_SIZE(msm8992_cci_rates) - 1 &&
	     rate > msm8992_cci_rates[i]; i++)
		;
	return msm8992_cci_rates[i];
}

static int msm8992_cci_set_rate(struct clk_hw *hw, unsigned long rate,
				unsigned long parent_rate)
{
	struct msm8992_cci_clk *c = to_cci_clk(hw);
	unsigned long parent = parent_rate, vco;
	u32 mode, user, lock, hf, div;
	int ret;

	if (rate != (unsigned long)msm8992_cci_round_rate(hw, rate, &parent))
		return -EINVAL;
	/* Reduce the current clock before selecting the 150 MHz safe path. */
	ret = msm8992_cci_mux(c, GENMASK(6, 5), 3 << 5);
	if (ret)
		return ret;
	ret = msm8992_cci_mux(c, GENMASK(2, 1), 1 << 1);
	if (ret)
		return ret;
	ret = msm8992_cci_mux(c, GENMASK(4, 3), 1 << 3);
	if (ret)
		return ret;
	mode = readl(c->pll + PLL_MODE) & ~GENMASK(2, 0);
	writel(mode, c->pll + PLL_MODE);
	readl(c->pll + PLL_MODE);
	if (rate == 150000000 || rate == 300000000 || rate == 600000000)
		return msm8992_cci_mux(c, GENMASK(6, 5),
				      (600000000 / rate - 1) << 5);
	/* All factory CCI points can use integral L values, without alpha. */
	div = rate == 134400000 ? 3 : 1;
	hf = rate < 500000000 ? 2 : 3;
	vco = rate * div * (hf == 2 ? 2 : 1);
	writel(vco / 19200000, c->pll + PLL_L);
	writel(0, c->pll + PLL_ALPHA);
	writel(0, c->pll + 0x0c);
	user = readl(c->pll + PLL_USER);
	user &= ~(GENMASK(21, 20) | GENMASK(11, 8) | GENMASK(3, 0));
	user |= (2 << 20) | (1 << 8) | BIT(24) | 9;
	writel(user, c->pll + PLL_USER);
	mode |= BIT(1);
	writel(mode, c->pll + PLL_MODE);
	readl(c->pll + PLL_MODE);
	udelay(5);
	mode |= BIT(2);
	writel(mode, c->pll + PLL_MODE);
	readl(c->pll + PLL_MODE);
	ret = readl_poll_timeout_atomic(c->pll + PLL_MODE, lock,
				       lock & BIT(31), 1, 1000);
	if (ret) {
		writel(mode & ~GENMASK(2, 0), c->pll + PLL_MODE);
		return ret;
	}
	writel(mode | BIT(0), c->pll + PLL_MODE);
	readl(c->pll + PLL_MODE);
	ret = msm8992_cci_mux(c, GENMASK(4, 3), hf << 3);
	if (ret)
		return ret;
	return msm8992_cci_mux(c, GENMASK(6, 5), (div - 1) << 5);
}

static const struct clk_ops msm8992_cci_ops = {
	.recalc_rate = msm8992_cci_recalc_rate,
	.round_rate = msm8992_cci_round_rate,
	.set_rate = msm8992_cci_set_rate,
};

static const struct clk_ops msm8992_cci_observe_ops = {
	.recalc_rate = msm8992_cci_recalc_rate,
};

static void __iomem *msm8992_map_cluster_mux(struct platform_device *pdev,
					  unsigned int cluster)
{
	struct resource *res;
	void __iomem *base;

	if (cluster)
		return devm_platform_ioremap_resource(pdev, cluster + 2);
	/*
	 * APCS IPC owns f900d000..f900efff and uses its mailbox register at
	 * +0x8. The A53 clock mux at +0x54 shares that bank, just as the
	 * early ACC boot code does. Do not claim it a second time.
	 */
	res = platform_get_resource(pdev, IORESOURCE_MEM, 2);
	if (!res)
		return ERR_PTR(-EINVAL);
	base = devm_ioremap(&pdev->dev, res->start, resource_size(res));
	return base ? base : ERR_PTR(-ENOMEM);
}

static int msm8992_cluster_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct clk_hw_onecell_data *clks;
	struct clk *xo, *aux;
	const struct clk_hw *aux_hw;
	int i, ret;

	if (!clusters_probe) {
		dev_info(dev, "MSM8992 cluster/CCI clocks held for manual probe\n");
		return -ENODEV;
	}

	xo = devm_clk_get(dev, "xo");
	if (IS_ERR(xo))
		return dev_err_probe(dev, PTR_ERR(xo), "cannot get XO\n");
	aux = devm_clk_get(dev, "aux");
	if (IS_ERR(aux))
		return dev_err_probe(dev, PTR_ERR(aux), "cannot get auxiliary clock\n");
	if (clk_get_rate(xo) != 19200000 || clk_get_rate(aux) != 600000000)
		return dev_err_probe(dev, -EINVAL, "unexpected reference clock rates\n");
	aux_hw = __clk_get_hw(aux);
	clks = devm_kzalloc(dev, struct_size(clks, hws, 3), GFP_KERNEL);
	if (!clks)
		return -ENOMEM;
	clks->num = 3;
	/* Factory NOMINAL corner 5 is encoded as 4 in the RPM/GENPD interface. */
	if (!clocks_observe) {
		ret = dev_pm_genpd_set_performance_state(dev, 4);
		if (ret)
			return dev_err_probe(dev, ret, "cannot vote PLL digital supply\n");
		pm_runtime_enable(dev);
		ret = pm_runtime_resume_and_get(dev);
		if (ret < 0)
			goto clear_vote;
	}
	for (i = 0; i < 2; i++) {
		struct msm8992_cluster_clk *c;
		struct clk_init_data init = {
			.name = i ? "msm8992_a57" : "msm8992_a53",
			.ops = &msm8992_cluster_ops,
			.flags = CLK_IS_CRITICAL | CLK_GET_RATE_NOCACHE,
			.parent_hws = &aux_hw,
			.num_parents = 1,
		};
		if (clocks_observe) {
			init.ops = clocks_test ? &msm8992_cluster_ops : &msm8992_cluster_observe_ops;
			init.flags = CLK_GET_RATE_NOCACHE;
			dev_info(dev, "clock observation: mapping %s registers\n", init.name);
		}

		c = devm_kzalloc(dev, sizeof(*c), GFP_KERNEL);
		if (!c) {
			ret = -ENOMEM;
			goto put_pm;
		}
		c->pll = devm_platform_ioremap_resource(pdev, i);
		if (IS_ERR(c->pll)) {
			ret = PTR_ERR(c->pll);
			goto put_pm;
		}
		c->mux = msm8992_map_cluster_mux(pdev, i);
		if (IS_ERR(c->mux)) {
			ret = PTR_ERR(c->mux);
			goto put_pm;
		}
		c->cluster = i;
		c->xo_rate = clk_get_rate(xo);
		c->hw.init = &init;
		ret = devm_clk_hw_register(dev, &c->hw);
		if (ret)
			goto put_pm;
		clks->hws[i] = &c->hw;
	}
	{
		struct msm8992_cci_clk *c;
		struct resource *res;
		struct clk_init_data init = {
			.name = "msm8992_cci",
			.ops = &msm8992_cci_ops,
			.flags = CLK_IS_CRITICAL | CLK_GET_RATE_NOCACHE,
			.parent_hws = &aux_hw,
			.num_parents = 1,
		};
		if (clocks_observe) {
			init.ops = cci_test ? &msm8992_cci_ops : &msm8992_cci_observe_ops;
			init.flags = CLK_GET_RATE_NOCACHE;
			dev_info(dev, "clock observation: mapping CCI PLL and reading secure mux\n");
		}

		c = devm_kzalloc(dev, sizeof(*c), GFP_KERNEL);
		if (!c) {
			ret = -ENOMEM;
			goto put_pm;
		}
		c->pll = devm_platform_ioremap_resource(pdev, 4);
		if (IS_ERR(c->pll)) {
			ret = PTR_ERR(c->pll);
			goto put_pm;
		}
		res = platform_get_resource(pdev, IORESOURCE_MEM, 5);
		if (!res) {
			ret = -EINVAL;
			goto put_pm;
		}
		c->mux = res->start;
		c->hw.init = &init;
		ret = devm_clk_hw_register(dev, &c->hw);
		if (ret)
			goto put_pm;
		clks->hws[2] = &c->hw;
	}
	ret = devm_of_clk_add_hw_provider(dev, of_clk_hw_onecell_get, clks);
	if (!ret) {
		dev_info(dev, "MSM8992 A53/A57/CCI clocks registered%s\n",
			 clocks_observe ? (cci_test ? " (manual CPU/CCI clock test)" :
			 clocks_test ? " (manual CPU clock test, CCI read-only)" :
			 " (read-only, no supply/rate writes)") : "");
		return 0;
	}
put_pm:
	if (!clocks_observe)
		pm_runtime_put_sync(dev);
clear_vote:
	if (!clocks_observe) {
		pm_runtime_disable(dev);
		dev_pm_genpd_set_performance_state(dev, 0);
	}
	return ret;
}

static unsigned long msm8992_cpu_recalc_rate(struct clk_hw *hw,
					    unsigned long parent_rate)
{
	return parent_rate;
}

static const struct clk_ops msm8992_cpu_clk_ops = {
	.recalc_rate = msm8992_cpu_recalc_rate,
};

static int msm8992_cpu_clk_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct clk_hw *hw;
	struct clk_init_data init = {
		.name = "msm8992_cpu_aux",
		.ops = &msm8992_cpu_clk_ops,
		.flags = CLK_IS_CRITICAL,
		.parent_data = &(const struct clk_parent_data) { .fw_name = "aux" },
		.num_parents = 1,
	};
	int ret;

	if (of_device_is_compatible(dev->of_node, "qcom,msm8992-cpu-clock"))
		return msm8992_cluster_probe(pdev);

	hw = devm_kzalloc(dev, sizeof(*hw), GFP_KERNEL);
	if (!hw)
		return -ENOMEM;
	hw->init = &init;
	ret = devm_clk_hw_register(dev, hw);
	if (ret)
		return ret;
	return devm_of_clk_add_hw_provider(dev, of_clk_hw_simple_get, hw);
}

static const struct of_device_id msm8992_cpu_clk_match[] = {
	{ .compatible = "qcom,msm8992-cpu-aux-clock" },
	{ .compatible = "qcom,msm8992-cpu-clock" },
	{ }
};
MODULE_DEVICE_TABLE(of, msm8992_cpu_clk_match);

static struct platform_driver msm8992_cpu_clk_driver = {
	.probe = msm8992_cpu_clk_probe,
	.driver = {
		.name = "msm8992-cpu-aux-clock",
		.of_match_table = msm8992_cpu_clk_match,
		.suppress_bind_attrs = true,
	},
};
builtin_platform_driver(msm8992_cpu_clk_driver);
