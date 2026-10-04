// SPDX-License-Identifier: GPL-2.0-only
/* MSM8992 auxiliary CPU clock, selected by the legacy CPU boot protocol. */

#include <linux/clk-provider.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>

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
	{ }
};
MODULE_DEVICE_TABLE(of, msm8992_cpu_clk_match);

static struct platform_driver msm8992_cpu_clk_driver = {
	.probe = msm8992_cpu_clk_probe,
	.driver = {
		.name = "msm8992-cpu-aux-clock",
		.of_match_table = msm8992_cpu_clk_match,
	},
};
builtin_platform_driver(msm8992_cpu_clk_driver);
