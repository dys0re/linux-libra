// SPDX-License-Identifier: GPL-2.0-only
/*
 * MSM8992/8994 USB2 PHY, based on Qualcomm's phy-msm-hsusb.c.
 * Copyright (c) 2012-2014, The Linux Foundation. All rights reserved.
 */

#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/phy/phy.h>
#include <linux/platform_device.h>
#include <linux/pm_domain.h>
#include <linux/pm_runtime.h>
#include <linux/regulator/consumer.h>
#include <linux/reset.h>

#define HS_PHY_CTRL			0x10
#define RETENABLEN			BIT(1)
#define VBUSVLDEXT			BIT(13)
#define UTMI_OTG_VBUS_VALID		BIT(20)
#define USB2_UTMI_CLK_EN			BIT(21)
#define SW_SESSVLD_SEL			BIT(28)
#define CLAMP_MPM_DPSE_DMSE_EN_N		BIT(26)

#define PARAMETER_OVERRIDE_X		0x14
#define PARAMETER_OVERRIDE_MASK		GENMASK(25, 0)
#define HS_PHY_CTRL_COMMON		0xec
#define COMMON_PLLBTUNE			BIT(15)
#define COMMON_PLLITUNE_1		BIT(18)
#define MSM_CORE_VER_120			0x10020061
#define COMMON_CLKCORE			BIT(14)
#define COMMON_VBUSVLDEXTSEL		BIT(12)
#define COMMON_OTGDISABLE		BIT(11)
#define COMMON_OTGTUNE_MASK		GENMASK(10, 8)
#define COMMON_OTGTUNE_DEFAULT		(4 << 8)
#define COMMON_COMMONONN			BIT(7)
#define COMMON_FSEL			GENMASK(6, 4)
#define COMMON_RETENABLEN		BIT(3)

#define PHY_CTRL_COMMON0			0x78
#define PHY_COMMONONN			BIT(7)
#define PHY_RETENABLEN			BIT(3)
#define PHY_CTRL2			0x90
#define PHY_SUSPEND_N_SEL			BIT(7)
#define PHY_SUSPEND_N			BIT(6)
#define PHY_CFG0				0xc4
#define PHY_OVERRIDE_EN			GENMASK(2, 0)
#define PHY_REFCLK_CTRL			0xe8
#define REFCLK_RXTAP_EN			BIT(0)
#define PHY_PWRDOWN_CTRL			0xec
#define PWRDN_B				BIT(0)

struct msm8992_hsphy {
	void __iomem *csr;
	void __iomem *qscratch;
	struct clk_bulk_data clks[3];
	struct regulator_bulk_data supplies[2];
	struct reset_control *reset;
	struct dev_pm_domain_list *domains;
	u32 tuning;
	u32 core_ver;
	enum phy_mode mode;
};

static void hsphy_update(void __iomem *base, u32 offset, u32 mask, u32 value)
{
	u32 val = readl(base + offset);

	writel((val & ~mask) | value, base + offset);
	readl(base + offset);
}

static int msm8992_hsphy_init(struct phy *phy)
{
	struct msm8992_hsphy *priv = phy_get_drvdata(phy);
	int ret, i;

	for (i = 0; i < priv->domains->num_pds; i++) {
		ret = pm_runtime_resume_and_get(priv->domains->pd_devs[i]);
		if (ret < 0) {
			dev_err(&phy->dev, "%s power domain resume failed: %d\n",
				i ? "MX" : "CX", ret);
			goto put_domains;
		}
	}

	ret = regulator_bulk_enable(ARRAY_SIZE(priv->supplies), priv->supplies);
	if (ret)
		goto put_domains;

	ret = clk_bulk_prepare_enable(ARRAY_SIZE(priv->clks), priv->clks);
	if (ret)
		goto disable_supplies;

	ret = reset_control_assert(priv->reset);
	if (ret)
		goto disable_clocks;
	usleep_range(1000, 1200);
	ret = reset_control_deassert(priv->reset);
	if (ret)
		goto disable_clocks;
	priv->core_ver = readl(priv->qscratch);

	hsphy_update(priv->qscratch, HS_PHY_CTRL,
		     USB2_UTMI_CLK_EN | CLAMP_MPM_DPSE_DMSE_EN_N | RETENABLEN,
		     USB2_UTMI_CLK_EN | CLAMP_MPM_DPSE_DMSE_EN_N | RETENABLEN);
	usleep_range(2000, 2200);

	/* MSM8992 uses the common control register and PLLBTUNE workaround. */
	hsphy_update(priv->qscratch, HS_PHY_CTRL_COMMON,
		     COMMON_FSEL | COMMON_OTGDISABLE | COMMON_OTGTUNE_MASK |
		     COMMON_COMMONONN | COMMON_RETENABLEN | COMMON_PLLBTUNE |
		     COMMON_CLKCORE,
		     COMMON_OTGDISABLE | COMMON_OTGTUNE_DEFAULT |
		     COMMON_COMMONONN | COMMON_RETENABLEN | COMMON_PLLBTUNE |
		     COMMON_CLKCORE);
	hsphy_update(priv->qscratch, PARAMETER_OVERRIDE_X,
		     PARAMETER_OVERRIDE_MASK, priv->tuning);

	return 0;

disable_clocks:
	clk_bulk_disable_unprepare(ARRAY_SIZE(priv->clks), priv->clks);
disable_supplies:
	regulator_bulk_disable(ARRAY_SIZE(priv->supplies), priv->supplies);
put_domains:
	while (--i >= 0)
		pm_runtime_put_sync(priv->domains->pd_devs[i]);
	return ret;
}

static int msm8992_hsphy_exit(struct phy *phy)
{
	struct msm8992_hsphy *priv = phy_get_drvdata(phy);
	int i;

	reset_control_assert(priv->reset);
	clk_bulk_disable_unprepare(ARRAY_SIZE(priv->clks), priv->clks);
	regulator_bulk_disable(ARRAY_SIZE(priv->supplies), priv->supplies);
	for (i = priv->domains->num_pds - 1; i >= 0; i--)
		pm_runtime_put_sync(priv->domains->pd_devs[i]);

	return 0;
}

static void msm8992_hsphy_apply_mode(struct msm8992_hsphy *priv)
{
	bool peripheral = priv->mode == PHY_MODE_USB_DEVICE ||
			  priv->mode == PHY_MODE_USB_DEVICE_LS ||
			  priv->mode == PHY_MODE_USB_DEVICE_FS ||
			  priv->mode == PHY_MODE_USB_DEVICE_HS;

	hsphy_update(priv->qscratch, HS_PHY_CTRL_COMMON,
		     COMMON_VBUSVLDEXTSEL, peripheral ? COMMON_VBUSVLDEXTSEL : 0);
	hsphy_update(priv->qscratch, HS_PHY_CTRL,
		     VBUSVLDEXT | UTMI_OTG_VBUS_VALID | SW_SESSVLD_SEL,
		     peripheral ? VBUSVLDEXT | UTMI_OTG_VBUS_VALID | SW_SESSVLD_SEL : 0);
}

static int msm8992_hsphy_power_on(struct phy *phy)
{
	struct msm8992_hsphy *priv = phy_get_drvdata(phy);

	hsphy_update(priv->csr, PHY_PWRDOWN_CTRL, PWRDN_B, PWRDN_B);
	hsphy_update(priv->csr, PHY_REFCLK_CTRL, REFCLK_RXTAP_EN, REFCLK_RXTAP_EN);
	hsphy_update(priv->csr, PHY_CTRL_COMMON0, PHY_COMMONONN | PHY_RETENABLEN,
		     PHY_COMMONONN | PHY_RETENABLEN);
	hsphy_update(priv->csr, PHY_CTRL2, PHY_SUSPEND_N_SEL | PHY_SUSPEND_N, 0);
	hsphy_update(priv->csr, PHY_CFG0, PHY_OVERRIDE_EN, 0);
	hsphy_update(priv->qscratch, HS_PHY_CTRL_COMMON,
		     COMMON_RETENABLEN | COMMON_OTGDISABLE |
		     (priv->core_ver == MSM_CORE_VER_120 ? COMMON_PLLITUNE_1 : 0),
		     COMMON_RETENABLEN);
	msm8992_hsphy_apply_mode(priv);
	usleep_range(80, 100);

	return 0;
}

static int msm8992_hsphy_power_off(struct phy *phy)
{
	struct msm8992_hsphy *priv = phy_get_drvdata(phy);

	hsphy_update(priv->qscratch, HS_PHY_CTRL,
		     VBUSVLDEXT | UTMI_OTG_VBUS_VALID | SW_SESSVLD_SEL, 0);
	/* Keep the analogue rails enabled, as required by vdda-force-on. */
	/* On core 1.2.0 the PLLITUNE[1] bit, not RETENABLEN, controls retention. */
	if (priv->core_ver == MSM_CORE_VER_120)
		hsphy_update(priv->qscratch, HS_PHY_CTRL_COMMON,
			     COMMON_PLLITUNE_1, COMMON_PLLITUNE_1);
	else
		hsphy_update(priv->qscratch, HS_PHY_CTRL_COMMON, COMMON_RETENABLEN, 0);
	hsphy_update(priv->csr, PHY_CFG0, PHY_OVERRIDE_EN, PHY_OVERRIDE_EN);
	hsphy_update(priv->csr, PHY_CTRL2, PHY_SUSPEND_N_SEL | PHY_SUSPEND_N,
		     PHY_SUSPEND_N_SEL);
	hsphy_update(priv->csr, PHY_CTRL_COMMON0, PHY_COMMONONN | PHY_RETENABLEN, 0);
	hsphy_update(priv->csr, PHY_REFCLK_CTRL, REFCLK_RXTAP_EN, 0);
	hsphy_update(priv->csr, PHY_PWRDOWN_CTRL, PWRDN_B, 0);

	return 0;
}

static int msm8992_hsphy_set_mode(struct phy *phy, enum phy_mode mode, int submode)
{
	struct msm8992_hsphy *priv = phy_get_drvdata(phy);

	priv->mode = mode;
	if (phy->power_count)
		msm8992_hsphy_apply_mode(priv);
	return 0;
}

static const struct phy_ops msm8992_hsphy_ops = {
	.init = msm8992_hsphy_init,
	.exit = msm8992_hsphy_exit,
	.power_on = msm8992_hsphy_power_on,
	.power_off = msm8992_hsphy_power_off,
	.set_mode = msm8992_hsphy_set_mode,
	.owner = THIS_MODULE,
};

static int msm8992_hsphy_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct dev_pm_domain_attach_data pd_data = {
		.pd_flags = PD_FLAG_NO_DEV_LINK,
	};
	struct msm8992_hsphy *priv;
	struct phy_provider *provider;
	struct resource *res;
	struct phy *phy;
	int ret;

	priv = devm_kzalloc(dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	priv->csr = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(priv->csr))
		return PTR_ERR(priv->csr);

	/* QSCRATCH is shared with the DWC3 glue, which owns the resource. */
	res = platform_get_resource(pdev, IORESOURCE_MEM, 1);
	if (!res)
		return -EINVAL;
	priv->qscratch = devm_ioremap(dev, res->start, resource_size(res));
	if (!priv->qscratch)
		return -ENOMEM;

	priv->clks[0].id = "ref";
	priv->clks[1].id = "ahb";
	priv->clks[2].id = "sleep";
	ret = devm_clk_bulk_get(dev, ARRAY_SIZE(priv->clks), priv->clks);
	if (ret)
		return dev_err_probe(dev, ret, "failed to get clocks\n");

	priv->reset = devm_reset_control_get_exclusive(dev, NULL);
	if (IS_ERR(priv->reset))
		return dev_err_probe(dev, PTR_ERR(priv->reset), "failed to get reset\n");

	priv->supplies[0].supply = "vdda1p8";
	priv->supplies[0].init_load_uA = 19000;
	priv->supplies[1].supply = "vdda3p3";
	priv->supplies[1].init_load_uA = 16000;
	ret = devm_regulator_bulk_get(dev, ARRAY_SIZE(priv->supplies), priv->supplies);
	if (ret)
		return dev_err_probe(dev, ret, "failed to get supplies\n");

	ret = devm_pm_domain_attach_list(dev, &pd_data, &priv->domains);
	if (ret < 0)
		return dev_err_probe(dev, ret, "failed to attach power domains\n");
	if (ret != 2)
		return dev_err_probe(dev, -EINVAL, "CX and MX domains are required\n");

	ret = device_property_read_u32(dev, "qcom,hsphy-init", &priv->tuning);
	if (ret)
		return ret;
	if (priv->tuning & ~PARAMETER_OVERRIDE_MASK)
		return -EINVAL;

	ret = regulator_set_voltage(priv->supplies[0].consumer, 1800000, 1800000);
	if (ret)
		return ret;
	ret = regulator_set_voltage(priv->supplies[1].consumer, 3050000, 3300000);
	if (ret)
		return ret;

	phy = devm_phy_create(dev, NULL, &msm8992_hsphy_ops);
	if (IS_ERR(phy))
		return PTR_ERR(phy);
	phy_set_drvdata(phy, priv);

	provider = devm_of_phy_provider_register(dev, of_phy_simple_xlate);
	return PTR_ERR_OR_ZERO(provider);
}

static const struct of_device_id msm8992_hsphy_match[] = {
	{ .compatible = "qcom,msm8992-usb-hs-phy" },
	{ }
};
MODULE_DEVICE_TABLE(of, msm8992_hsphy_match);

static struct platform_driver msm8992_hsphy_driver = {
	.probe = msm8992_hsphy_probe,
	.driver = {
		.name = "msm8992-usb-hs-phy",
		.of_match_table = msm8992_hsphy_match,
	},
};
module_platform_driver(msm8992_hsphy_driver);

MODULE_DESCRIPTION("Qualcomm MSM8992 USB2 PHY");
MODULE_LICENSE("GPL");
