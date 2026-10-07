// SPDX-License-Identifier: GPL-2.0-only
/* MSM8992/8994 20nm PCIe QMP PHY, from the factory pci-msm sequence. */
#include <linux/clk.h>
#include <linux/clk-provider.h>
#include <linux/debugfs.h>
#include <linux/delay.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/phy/phy.h>
#include <linux/platform_device.h>
#include <linux/reset.h>
#include <linux/seq_file.h>

struct msm8992_pcie_phy {
	void __iomem *base;
	struct clk *pipe;
	struct reset_control *pipe_reset;
	struct phy *phy;
};

static int msm8992_pcie_phy_status_show(struct seq_file *s, void *data)
{
	struct msm8992_pcie_phy *p = dev_get_drvdata(s->private);
	/* Only registers read by the factory PHY dump; never scan the bank. */
	static const u16 regs[] = {
		0x150, 0x160, 0x57c, 0x600, 0x604, 0x608, 0x648,
		0x728, 0x72c, 0x730, 0x734, 0x738, 0x73c,
	};
	int i;

	mutex_lock(&p->phy->mutex);
	if (!p->phy->power_count) {
		seq_puts(s, "PHY is powered off\n");
		goto out;
	}
	for (i = 0; i < ARRAY_SIZE(regs); i++)
		seq_printf(s, "PHY+%03x=%08x\n", regs[i],
			   readl(p->base + regs[i]));
out:
	mutex_unlock(&p->phy->mutex);
	return 0;
}

static const struct {
	u16 offset;
	u8 value;
} msm8992_pcie_phy_init[] = {
	{ 0x604, 0x03 }, /* PCIE_PHY_POWER_DOWN_CONTROL */
	{ 0x048, 0x08 }, /* QSERDES_COM_SYSCLK_EN_SEL_TXBAND */
	{ 0x0ac, 0x82 }, /* QSERDES_COM_DEC_START1 */
	{ 0x10c, 0x03 }, /* QSERDES_COM_DEC_START2 */
	{ 0x100, 0xd5 }, /* QSERDES_COM_DIV_FRAC_START1 */
	{ 0x104, 0xaa }, /* QSERDES_COM_DIV_FRAC_START2 */
	{ 0x108, 0x4d }, /* QSERDES_COM_DIV_FRAC_START3 */
	{ 0x09c, 0x03 }, /* QSERDES_COM_PLLLOCK_CMP_EN */
	{ 0x090, 0x06 }, /* QSERDES_COM_PLLLOCK_CMP1 */
	{ 0x094, 0x1a }, /* QSERDES_COM_PLLLOCK_CMP2 */
	{ 0x114, 0x7c }, /* QSERDES_COM_PLL_CRCTRL */
	{ 0x034, 0x1f }, /* QSERDES_COM_PLL_CP_SETI */
	{ 0x038, 0x12 }, /* QSERDES_COM_PLL_IP_SETP */
	{ 0x03c, 0x0f }, /* QSERDES_COM_PLL_CP_SETP */
	{ 0x024, 0x01 }, /* QSERDES_COM_PLL_IP_SETI */
	{ 0x00c, 0x03 }, /* QSERDES_COM_IE_TRIM */
	{ 0x010, 0x00 }, /* QSERDES_COM_IP_TRIM */
	{ 0x0a0, 0xff }, /* QSERDES_COM_BGTC */
	{ 0x014, 0x46 }, /* QSERDES_COM_PLL_CNTRL */
	{ 0x400, 0xf4 }, /* QSERDES_RX_CDR_CONTROL1 */
	{ 0x408, 0x2c }, /* QSERDES_RX_CDR_CONTROL_HALF */
	{ 0x004, 0xe1 }, /* QSERDES_COM_PLL_VCOTAIL_EN */
	{ 0x04c, 0x91 }, /* QSERDES_COM_RESETSM_CNTRL */
	{ 0x050, 0x07 }, /* QSERDES_COM_RESETSM_CNTRL2 */
	{ 0x0e0, 0x20 }, /* QSERDES_COM_RES_CODE_START_SEG1 */
	{ 0x0e8, 0x77 }, /* QSERDES_COM_RES_CODE_CAL_CSR */
	{ 0x0f0, 0x15 }, /* QSERDES_COM_RES_TRIM_CONTROL */
	{ 0x268, 0x03 }, /* QSERDES_TX_RCV_DETECT_LVL */
	{ 0x414, 0x09 }, /* QSERDES_RX_UCDR_FO_GAIN */
	{ 0x418, 0x04 }, /* QSERDES_RX_UCDR_SO_GAIN */
	{ 0x41c, 0x49 }, /* QSERDES_RX_UCDR_SO_SATURATION_AND_ENABLE */
	{ 0x4a8, 0xff }, /* QSERDES_RX_RX_EQ_GAIN1_LSB */
	{ 0x4ac, 0x1f }, /* QSERDES_RX_RX_EQ_GAIN1_MSB */
	{ 0x4b0, 0xff }, /* QSERDES_RX_RX_EQ_GAIN2_LSB */
	{ 0x4b4, 0x00 }, /* QSERDES_RX_RX_EQ_GAIN2_MSB */
	{ 0x4bc, 0x1e }, /* QSERDES_RX_RX_EQU_ADAPTOR_CNTRL2 */
	{ 0x4f0, 0x67 }, /* QSERDES_RX_RX_EQ_OFFSET_ADAPTOR_CNTRL1 */
	{ 0x4f4, 0x80 }, /* QSERDES_RX_RX_OFFSET_ADAPTOR_CNTRL2 */
	{ 0x4f8, 0x40 }, /* QSERDES_RX_SIGDET_ENABLES */
	{ 0x500, 0xb0 }, /* QSERDES_RX_SIGDET_CNTRL */
	{ 0x504, 0x06 }, /* QSERDES_RX_SIGDET_DEGLITCH_CNTRL */
	{ 0x110, 0x10 }, /* QSERDES_COM_PLL_RXTXEPCLK_EN */
	{ 0x648, 0x10 }, /* PCIE_PHY_ENDPOINT_REFCLK_DRIVE */
	{ 0x650, 0xa3 }, /* PCIE_PHY_POWER_STATE_CONFIG1 */
	{ 0x654, 0x4b }, /* PCIE_PHY_POWER_STATE_CONFIG2 */
	{ 0x64c, 0x4d }, /* PCIE_PHY_RX_IDLE_DTCT_CNTRL */
	{ 0x600, 0x00 }, /* PCIE_PHY_SW_RESET */
	{ 0x608, 0x03 }, /* PCIE_PHY_START */
};

static void msm8992_pcie_phy_stop(struct msm8992_pcie_phy *p)
{
	writel(1, p->base + 0x600);
	writel(0, p->base + 0x604);
}

static int msm8992_pcie_phy_power_on(struct phy *phy)
{
	struct msm8992_pcie_phy *p = phy_get_drvdata(phy);
	u32 status;
	int ret, i;

	for (i = 0; i < ARRAY_SIZE(msm8992_pcie_phy_init); i++)
		writel(msm8992_pcie_phy_init[i].value,
		       p->base + msm8992_pcie_phy_init[i].offset);

	/* The PHY starts before GCC gates its 125 MHz PIPE output. */
	usleep_range(995, 1005);
	/* OEM clears the PIPE branch reset at GCC+0x1b14 before enabling it. */
	ret = reset_control_deassert(p->pipe_reset);
	if (ret)
		goto err_stop;
	ret = clk_set_rate(p->pipe, 125000000);
	if (ret)
		goto err_stop;
	ret = clk_prepare_enable(p->pipe);
	if (ret)
		goto err_stop;

	ret = readl_poll_timeout(p->base + 0x728, status, !(status & BIT(6)),
				 1000, 100000);
	if (ret) {
		dev_err(&phy->dev, "PCIe PHY not ready: status=%#x\n", status);
		clk_disable_unprepare(p->pipe);
		goto err_stop;
	}
	return 0;

err_stop:
	msm8992_pcie_phy_stop(p);
	reset_control_assert(p->pipe_reset);
	return ret;
}

static int msm8992_pcie_phy_power_off(struct phy *phy)
{
	struct msm8992_pcie_phy *p = phy_get_drvdata(phy);

	msm8992_pcie_phy_stop(p);
	clk_disable_unprepare(p->pipe);
	return reset_control_assert(p->pipe_reset);
}

static const struct phy_ops msm8992_pcie_phy_ops = {
	.power_on = msm8992_pcie_phy_power_on,
	.power_off = msm8992_pcie_phy_power_off,
	.owner = THIS_MODULE,
};

static int msm8992_pcie_phy_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct phy_provider *provider;
	struct msm8992_pcie_phy *p;
	struct clk_hw *pipe_hw;
	struct phy *phy;
	int ret;

	p = devm_kzalloc(dev, sizeof(*p), GFP_KERNEL);
	if (!p)
		return -ENOMEM;
	p->base = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(p->base))
		return PTR_ERR(p->base);
	p->pipe = devm_clk_get(dev, "pipe");
	if (IS_ERR(p->pipe))
		return dev_err_probe(dev, PTR_ERR(p->pipe), "PIPE clock unavailable\n");

	p->pipe_reset = devm_reset_control_get_exclusive(dev, "pipe");
	if (IS_ERR(p->pipe_reset))
		return dev_err_probe(dev, PTR_ERR(p->pipe_reset), "PIPE reset unavailable\n");

	/* Independent clock output: GCC must never treat PIPE as the XO. */
	pipe_hw = devm_clk_hw_register_fixed_rate(dev, "pcie0_phy_pipe", NULL, 0,
						125000000);
	if (IS_ERR(pipe_hw))
		return PTR_ERR(pipe_hw);
	ret = devm_of_clk_add_hw_provider(dev, of_clk_hw_simple_get, pipe_hw);
	if (ret)
		return ret;

	phy = devm_phy_create(dev, NULL, &msm8992_pcie_phy_ops);
	if (IS_ERR(phy))
		return PTR_ERR(phy);
	phy_set_drvdata(phy, p);
	p->phy = phy;
	debugfs_create_devm_seqfile(&phy->dev, "status", phy->debugfs,
				   msm8992_pcie_phy_status_show);
	provider = devm_of_phy_provider_register(dev, of_phy_simple_xlate);
	return PTR_ERR_OR_ZERO(provider);
}

static const struct of_device_id msm8992_pcie_phy_match[] = {
	{ .compatible = "qcom,msm8992-pcie-phy" },
	{}
};
MODULE_DEVICE_TABLE(of, msm8992_pcie_phy_match);

static struct platform_driver msm8992_pcie_phy_driver = {
	.probe = msm8992_pcie_phy_probe,
	.driver = {
		.name = "msm8992-pcie-phy",
		.of_match_table = msm8992_pcie_phy_match,
	},
};
module_platform_driver(msm8992_pcie_phy_driver);
MODULE_DESCRIPTION("Qualcomm MSM8992/8994 20nm PCIe PHY");
MODULE_LICENSE("GPL");
