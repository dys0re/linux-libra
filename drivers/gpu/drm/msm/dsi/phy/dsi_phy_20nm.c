// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (c) 2015, The Linux Foundation. All rights reserved.
 */

#include "dsi_phy.h"
#include "dsi.xml.h"
#include "dsi_phy_20nm.xml.h"
#include <linux/delay.h>
#include <linux/math64.h>
#include <linux/of.h>

/* MSM8992 PLL sequence from the downstream 20nm DSI PLL driver.
 * Copyright (c) 2014-2015, The Linux Foundation.
 * Copyright (C) 2016 XiaoMi, Inc.
 */
#define PLL_SYS_CLK_CTRL		0x000
#define PLL_VCOTAIL_EN		0x004
#define PLL_CMN_MODE		0x008
#define PLL_BIAS_EN		0x030
#define PLL_RESETSM_CTRL		0x04c
#define PLL_RESETSM_CTRL2		0x050
#define PLL_RESETSM_CTRL3		0x054
#define PLL_KVCO_CODE		0x074
#define PLL_LOCK_CMP1		0x090
#define PLL_LOCK_CMP2		0x094
#define PLL_LOCK_CMP3		0x098
#define PLL_LOCK_CMP_EN		0x09c
#define PLL_VCO_TUNE		0x0a8
#define PLL_DEC_START1		0x0ac
#define PLL_FRAC_START1		0x100
#define PLL_FRAC_START2		0x104
#define PLL_FRAC_START3		0x108
#define PLL_DEC_START2		0x10c
#define PLL_POST_DIV		0x140
#define PLL_BYTE_DIV		0x144
#define PLL_PIXEL_DIV		0x148
#define PLL_RESET_SM		0x150
#define PLL_POLL_MAX_READS	15
#define PLL_POLL_INTERVAL_US	1000

struct dsi_20nm_divider {
	struct clk_hw hw;
	u32 *config;
	u8 shift;
	u8 width;
	u8 flags;
};

struct dsi_20nm_mux {
	struct clk_hw hw;
	u32 *config;
};

struct dsi_pll_20nm {
	struct clk_hw hw;
	struct msm_dsi_phy *phy;
	void __iomem *aux_base;
	unsigned long rate;
	/* Desired clock configuration survives PHY reset and GDSC off. */
	u32 post_div;
	u32 pixel_div;
	struct dsi_20nm_divider ndiv;
	struct dsi_20nm_divider pixel;
	struct dsi_20nm_mux byte_mux;
};

#define to_pll_20nm(ptr) container_of(ptr, struct dsi_pll_20nm, hw)
#define to_20nm_divider(ptr) container_of(ptr, struct dsi_20nm_divider, hw)
#define to_20nm_mux(ptr) container_of(ptr, struct dsi_20nm_mux, hw)

/* CCF queries these clocks while the PHY/analog rails may be off. */
static unsigned long dsi_20nm_div_recalc_rate(struct clk_hw *hw,
					   unsigned long parent_rate)
{
	struct dsi_20nm_divider *div = to_20nm_divider(hw);
	u32 val = (*div->config >> div->shift) & clk_div_mask(div->width);

	return divider_recalc_rate(hw, parent_rate, val, NULL,
				  div->flags, div->width);
}

static int dsi_20nm_div_determine_rate(struct clk_hw *hw,
				     struct clk_rate_request *req)
{
	struct dsi_20nm_divider *div = to_20nm_divider(hw);

	return divider_determine_rate(hw, req, NULL, div->width, div->flags);
}

static int dsi_20nm_div_set_rate(struct clk_hw *hw, unsigned long rate,
				unsigned long parent_rate)
{
	struct dsi_20nm_divider *div = to_20nm_divider(hw);
	u32 mask = clk_div_mask(div->width) << div->shift;
	int val;

	if (!rate)
		return -EINVAL;
	val = divider_get_val(rate, parent_rate, NULL, div->width, div->flags);
	if (val < 0)
		return val;
	*div->config = (*div->config & ~mask) | ((u32)val << div->shift);
	return 0;
}

static const struct clk_ops dsi_20nm_div_ops = {
	.recalc_rate = dsi_20nm_div_recalc_rate,
	.determine_rate = dsi_20nm_div_determine_rate,
	.set_rate = dsi_20nm_div_set_rate,
};

static u8 dsi_20nm_mux_get_parent(struct clk_hw *hw)
{
	return !!(*to_20nm_mux(hw)->config & BIT(5));
}

static int dsi_20nm_mux_set_parent(struct clk_hw *hw, u8 index)
{
	struct dsi_20nm_mux *mux = to_20nm_mux(hw);

	if (index > 1)
		return -EINVAL;
	*mux->config = (*mux->config & ~BIT(5)) | ((u32)index << 5);
	return 0;
}

static int dsi_20nm_mux_determine_rate(struct clk_hw *hw,
				     struct clk_rate_request *req)
{
	return clk_mux_determine_rate_flags(hw, req, 0);
}

static const struct clk_ops dsi_20nm_mux_ops = {
	.get_parent = dsi_20nm_mux_get_parent,
	.set_parent = dsi_20nm_mux_set_parent,
	.determine_rate = dsi_20nm_mux_determine_rate,
};

static void pll_20nm_powerdown(void __iomem *base)
{
	writel(0, base + PLL_SYS_CLK_CTRL);
	writel(1, base + PLL_CMN_MODE);
	writel(0x82, base + PLL_VCOTAIL_EN);
	writel(2, base + PLL_BIAS_EN);
	writel(6, base + PLL_RESETSM_CTRL3);
}

static void pll_20nm_bias_enable(void __iomem *base)
{
	writel(0x82, base + PLL_VCOTAIL_EN);
	writel(0x2a, base + PLL_BIAS_EN);
	writel(0x2b, base + PLL_BIAS_EN);
	writel(2, base + PLL_RESETSM_CTRL3);
}

static int pll_20nm_set_rate(struct clk_hw *hw, unsigned long rate,
			   unsigned long parent_rate)
{
	struct dsi_pll_20nm *pll = to_pll_20nm(hw);

	if (rate < pll->phy->cfg->min_pll_rate ||
	    rate > pll->phy->cfg->max_pll_rate || parent_rate != 19200000)
		return -EINVAL;

	pll->rate = rate;
	return 0;
}

static long pll_20nm_round_rate(struct clk_hw *hw, unsigned long rate,
			      unsigned long *parent_rate)
{
	struct msm_dsi_phy *phy = to_pll_20nm(hw)->phy;

	return clamp(rate, phy->cfg->min_pll_rate, phy->cfg->max_pll_rate);
}

static unsigned long pll_20nm_recalc_rate(struct clk_hw *hw,
					unsigned long parent_rate)
{
	/* set_rate caches the requested rate; register state is lost at GDSC off. */
	return to_pll_20nm(hw)->rate;
}

static int pll_20nm_poll_status(void __iomem *base, u32 mask, u32 *status)
{
	unsigned int i;

	/* Downstream readl_poll_timeout_noirq() takes a read count followed
	 * by an inter-read delay, unlike mainline readl_poll_timeout().
	 * Keep its 15 reads at 1 ms intervals for each hardware status bit.
	 */
	for (i = 0; i < PLL_POLL_MAX_READS; i++) {
		*status = readl(base + PLL_RESET_SM);
		if (*status & mask)
			return 0;
		udelay(PLL_POLL_INTERVAL_US);
	}

	return -ETIMEDOUT;
}

static int pll_20nm_prepare(struct clk_hw *hw)
{
	struct dsi_pll_20nm *pll = to_pll_20nm(hw);
	struct msm_dsi_phy *phy = pll->phy;
	void __iomem *base = phy->pll_base;
	u64 multiple, comparator;
	u32 dec, frac, status;
	const char *stage = "calibration";
	int ret;
	static const struct { u16 reg; u8 val; } config[] = {
		{ 0x000, 0x40 }, { 0x00c, 0x0f }, { 0x010, 0x0f },
		{ 0x018, 0x08 }, { 0x01c, 0x0e }, { 0x02c, 0x08 },
		{ 0x048, 0x4a },
		{ 0x060, 0x00 }, { 0x064, 0x01 }, { 0x014, 0x07 },
		{ 0x070, 0x1f }, { 0x068, 0x8a }, { 0x080, 0x10 },
		{ 0x0b4, 0x00 }, { 0x0fc, 0x0c }, { 0x110, 0x0a },
		{ 0x13c, 0x0f }, { 0x008, 0x00 },
		{ 0x024, 0x03 }, { 0x034, 0x3f }, { 0x038, 0x03 },
		{ 0x03c, 0x1f }, { 0x114, 0x77 },
	};
	unsigned int i;

	if (phy->pll_on)
		return 0;
	if (!pll->rate)
		return -EINVAL;
	ret = regulator_bulk_enable(phy->cfg->num_regulators, phy->supplies);
	if (ret)
		return dev_err_probe(&phy->pdev->dev, ret, "DSI PLL supplies failed\n");

	writel(pll->post_div, base + PLL_POST_DIV);
	writel(3, base + PLL_BYTE_DIV);
	writel(pll->pixel_div, base + PLL_PIXEL_DIV);
	dev_info(&phy->pdev->dev,
		 "DSI PLL start: vco=%lu ref=19200000 post=%#x pixel=%#x\n",
		 pll->rate, pll->post_div, pll->pixel_div);

	/* The unused PLL1 bias block participates in PLL0 calibration. */
	pll_20nm_bias_enable(pll->aux_base);
	pll_20nm_bias_enable(base);
	for (i = 0; i < ARRAY_SIZE(config); i++)
		writel(config[i].val, base + config[i].reg);

	/* 90-degree phase mode, 19.2 MHz reference, 20-bit fractional divider. */
	multiple = div_u64((u64)pll->rate << 20, 2 * 19200000);
	dec = multiple >> 20;
	frac = multiple & GENMASK(19, 0);
	comparator = div_u64(multiple * 2 * 127, 10 * BIT(20));
	writel((frac & 0x7f) | BIT(7), base + PLL_FRAC_START1);
	writel(((frac >> 7) & 0x7f) | BIT(7), base + PLL_FRAC_START2);
	writel(((frac >> 14) & 0x3f) | BIT(6), base + PLL_FRAC_START3);
	writel((dec & 0x7f) | BIT(7), base + PLL_DEC_START1);
	writel(((dec >> 7) & 1) | BIT(1), base + PLL_DEC_START2);
	writel(comparator & 0xff, base + PLL_LOCK_CMP1);
	writel((comparator >> 8) & 0xff, base + PLL_LOCK_CMP2);
	writel((comparator >> 16) & 0xff, base + PLL_LOCK_CMP3);
	writel(0x0d, base + PLL_LOCK_CMP_EN);

	/* Always calibrate on a cold start; dynamic refresh is not supported. */
	writel(0, base + PLL_KVCO_CODE);
	writel(0, base + PLL_VCO_TUNE);
	writel(0x24, base + PLL_RESETSM_CTRL);
	writel(0x07, base + PLL_RESETSM_CTRL2);
	writel(0x03, base + PLL_VCOTAIL_EN);
	writel(0x02, base + PLL_RESETSM_CTRL3);
	udelay(10);
	writel(0x03, base + PLL_RESETSM_CTRL3);
	writel(0, phy->base + REG_DSI_20nm_PHY_CTRL_1);
	writel(0x7f, phy->base + REG_DSI_20nm_PHY_CTRL_0);

	ret = pll_20nm_poll_status(base, BIT(5), &status);
	if (!ret) {
		stage = "ready";
		ret = pll_20nm_poll_status(base, BIT(6), &status);
	}
	if (ret) {
		/* Capture while the PHY's power/clocks and analog rails are on. */
		dev_err(&phy->pdev->dev,
			"DSI PLL %s timeout: status=%#x phsel=%#x iptat=%#x post=%#x pixel=%#x dec=%#x frac=%#x/%#x/%#x\n",
			stage, status, readl(base + 0x018), readl(base + 0x01c),
			readl(base + PLL_POST_DIV), readl(base + PLL_PIXEL_DIV),
			readl(base + PLL_DEC_START1), readl(base + PLL_FRAC_START1),
			readl(base + PLL_FRAC_START2), readl(base + PLL_FRAC_START3));
		pll_20nm_powerdown(pll->aux_base);
		pll_20nm_powerdown(base);
		regulator_bulk_disable(phy->cfg->num_regulators, phy->supplies);
		return dev_err_probe(&phy->pdev->dev, ret, "DSI PLL failed to lock\n");
	}
	pll_20nm_powerdown(pll->aux_base);
	phy->pll_on = true;
	dev_info(&phy->pdev->dev, "DSI PLL locked: vco=%lu status=%#x\n",
		 pll->rate, status);
	return 0;
}

static void pll_20nm_unprepare(struct clk_hw *hw)
{
	struct dsi_pll_20nm *pll = to_pll_20nm(hw);

	if (!pll->phy->pll_on)
		return;
	pll_20nm_powerdown(pll->aux_base);
	pll_20nm_powerdown(pll->phy->pll_base);
	pll->phy->pll_on = false;
	regulator_bulk_disable(pll->phy->cfg->num_regulators, pll->phy->supplies);
}

static const struct clk_ops pll_20nm_ops = {
	.prepare = pll_20nm_prepare,
	.unprepare = pll_20nm_unprepare,
	.set_rate = pll_20nm_set_rate,
	.round_rate = pll_20nm_round_rate,
	.recalc_rate = pll_20nm_recalc_rate,
};

static int dsi_pll_20nm_8992_init(struct msm_dsi_phy *phy)
{
	struct device *dev = &phy->pdev->dev;
	struct dsi_pll_20nm *pll;
	struct clk_hw *indirect, *hw;
	char name[40];
	struct clk_init_data init = {
		.name = name,
		.ops = &pll_20nm_ops,
		.parent_data = &(const struct clk_parent_data) { .fw_name = "ref" },
		.num_parents = 1,
		.flags = CLK_IGNORE_UNUSED | CLK_SET_RATE_GATE,
	};
	struct clk_init_data div_init = {
		.name = name,
		.ops = &dsi_20nm_div_ops,
		.num_parents = 1,
		.flags = CLK_SET_RATE_PARENT | CLK_SET_RATE_GATE,
	};
	struct clk_init_data mux_init = {
		.name = name,
		.ops = &dsi_20nm_mux_ops,
		.num_parents = 2,
		.flags = CLK_SET_RATE_PARENT | CLK_SET_PARENT_GATE,
	};
	int ret;

	pll = devm_kzalloc(dev, sizeof(*pll), GFP_KERNEL);
	if (!pll)
		return -ENOMEM;
	pll->phy = phy;
	pll->post_div = BIT(7) | 1;
	pll->aux_base = devm_platform_ioremap_resource_byname(phy->pdev, "dsi_pll_aux");
	if (IS_ERR(pll->aux_base))
		return PTR_ERR(pll->aux_base);
	snprintf(name, sizeof(name), "dsi%dvco_clk", phy->id);
	dev_info(dev, "MSM8992 DSI PLL: registering VCO\n");
	pll->hw.init = &init;
	ret = devm_clk_hw_register(dev, &pll->hw);
	if (ret)
		return ret;
	phy->vco_hw = &pll->hw;

	snprintf(name, sizeof(name), "dsi%dndiv", phy->id);
	dev_info(dev, "MSM8992 DSI PLL: registering N divider\n");
	div_init.parent_hws = (const struct clk_hw *[]){ &pll->hw };
	pll->ndiv.hw.init = &div_init;
	pll->ndiv.config = &pll->post_div;
	pll->ndiv.width = 4;
	pll->ndiv.flags = CLK_DIVIDER_ONE_BASED;
	ret = devm_clk_hw_register(dev, &pll->ndiv.hw);
	if (ret)
		return ret;
	snprintf(name, sizeof(name), "dsi%dindirect", phy->id);
	indirect = devm_clk_hw_register_fixed_factor_parent_hw(dev, name, &pll->ndiv.hw,
		CLK_SET_RATE_PARENT, 1, 2);
	if (IS_ERR(indirect))
		return PTR_ERR(indirect);

	snprintf(name, sizeof(name), "dsi%dbyte_mux", phy->id);
	dev_info(dev, "MSM8992 DSI PLL: registering byte mux\n");
	mux_init.parent_hws = (const struct clk_hw *[]){ &pll->hw, indirect };
	pll->byte_mux.hw.init = &mux_init;
	pll->byte_mux.config = &pll->post_div;
	ret = devm_clk_hw_register(dev, &pll->byte_mux.hw);
	if (ret)
		return ret;
	/* OCLK2 divider is fixed at four, followed by the byte divide-by-two. */
	snprintf(name, sizeof(name), "dsi%dpllbyte", phy->id);
	hw = devm_clk_hw_register_fixed_factor_parent_hw(dev, name, &pll->byte_mux.hw,
		CLK_SET_RATE_PARENT, 1, 8);
	if (IS_ERR(hw))
		return PTR_ERR(hw);
	phy->provided_clocks->hws[DSI_BYTE_PLL_CLK] = hw;

	snprintf(name, sizeof(name), "dsi%dpixel_div", phy->id);
	dev_info(dev, "MSM8992 DSI PLL: registering pixel divider\n");
	div_init.flags = CLK_SET_RATE_GATE;
	pll->pixel.hw.init = &div_init;
	pll->pixel.config = &pll->pixel_div;
	pll->pixel.width = 8;
	ret = devm_clk_hw_register(dev, &pll->pixel.hw);
	if (ret)
		return ret;
	snprintf(name, sizeof(name), "dsi%dpll", phy->id);
	hw = devm_clk_hw_register_fixed_factor_parent_hw(dev, name, &pll->pixel.hw,
		CLK_SET_RATE_PARENT, 1, 2);
	if (IS_ERR(hw))
		return PTR_ERR(hw);
	phy->provided_clocks->hws[DSI_PIXEL_PLL_CLK] = hw;
	dev_info(dev, "MSM8992 DSI PLL: output clocks registered\n");
	return 0;
}

static void dsi_20nm_dphy_set_timing(struct msm_dsi_phy *phy,
		struct msm_dsi_dphy_timing *timing)
{
	void __iomem *base = phy->base;

	writel(DSI_20nm_PHY_TIMING_CTRL_0_CLK_ZERO(timing->clk_zero),
	       base + REG_DSI_20nm_PHY_TIMING_CTRL_0);
	writel(DSI_20nm_PHY_TIMING_CTRL_1_CLK_TRAIL(timing->clk_trail),
	       base + REG_DSI_20nm_PHY_TIMING_CTRL_1);
	writel(DSI_20nm_PHY_TIMING_CTRL_2_CLK_PREPARE(timing->clk_prepare),
	       base + REG_DSI_20nm_PHY_TIMING_CTRL_2);
	writel((timing->clk_zero & BIT(8)) ?
	       DSI_20nm_PHY_TIMING_CTRL_3_CLK_ZERO_8 : 0,
	       base + REG_DSI_20nm_PHY_TIMING_CTRL_3);
	writel(DSI_20nm_PHY_TIMING_CTRL_4_HS_EXIT(timing->hs_exit),
	       base + REG_DSI_20nm_PHY_TIMING_CTRL_4);
	writel(DSI_20nm_PHY_TIMING_CTRL_5_HS_ZERO(timing->hs_zero),
	       base + REG_DSI_20nm_PHY_TIMING_CTRL_5);
	writel(DSI_20nm_PHY_TIMING_CTRL_6_HS_PREPARE(timing->hs_prepare),
	       base + REG_DSI_20nm_PHY_TIMING_CTRL_6);
	writel(DSI_20nm_PHY_TIMING_CTRL_7_HS_TRAIL(timing->hs_trail),
	       base + REG_DSI_20nm_PHY_TIMING_CTRL_7);
	writel(DSI_20nm_PHY_TIMING_CTRL_8_HS_RQST(timing->hs_rqst),
	       base + REG_DSI_20nm_PHY_TIMING_CTRL_8);
	writel(DSI_20nm_PHY_TIMING_CTRL_9_TA_GO(timing->ta_go) |
	       DSI_20nm_PHY_TIMING_CTRL_9_TA_SURE(timing->ta_sure),
	       base + REG_DSI_20nm_PHY_TIMING_CTRL_9);
	writel(DSI_20nm_PHY_TIMING_CTRL_10_TA_GET(timing->ta_get),
	       base + REG_DSI_20nm_PHY_TIMING_CTRL_10);
	writel(DSI_20nm_PHY_TIMING_CTRL_11_TRIG3_CMD(0),
	       base + REG_DSI_20nm_PHY_TIMING_CTRL_11);
}

static void dsi_20nm_phy_regulator_ctrl(struct msm_dsi_phy *phy, bool enable)
{
	void __iomem *base = phy->reg_base;

	if (!enable) {
		writel(0, base + REG_DSI_20nm_PHY_REGULATOR_CAL_PWR_CFG);
		return;
	}

	if (phy->regulator_ldo_mode) {
		writel(0x1d, phy->base + REG_DSI_20nm_PHY_LDO_CNTRL);
		return;
	}

	/* non LDO mode */
	writel(0x03, base + REG_DSI_20nm_PHY_REGULATOR_CTRL_1);
	writel(0x03, base + REG_DSI_20nm_PHY_REGULATOR_CTRL_2);
	writel(0x00, base + REG_DSI_20nm_PHY_REGULATOR_CTRL_3);
	writel(0x20, base + REG_DSI_20nm_PHY_REGULATOR_CTRL_4);
	writel(0x01, base + REG_DSI_20nm_PHY_REGULATOR_CAL_PWR_CFG);
	writel(0x00, phy->base + REG_DSI_20nm_PHY_LDO_CNTRL);
	writel(0x03, base + REG_DSI_20nm_PHY_REGULATOR_CTRL_0);
}

static int dsi_20nm_phy_enable(struct msm_dsi_phy *phy,
				struct msm_dsi_phy_clk_request *clk_req)
{
	struct msm_dsi_dphy_timing *timing = &phy->timing;
	int i;
	void __iomem *base = phy->base;
	u32 cfg_4[4] = {0x20, 0x40, 0x20, 0x00};
	u32 val;
	bool libra = phy->cfg == &dsi_phy_20nm_8992_cfgs &&
		     of_machine_is_compatible("xiaomi,libra");

	DBG("");

	if (msm_dsi_dphy_timing_calc(timing, clk_req)) {
		DRM_DEV_ERROR(&phy->pdev->dev,
			"%s: D-PHY timing calculation failed\n", __func__);
		return -EINVAL;
	}
	if (libra && clk_req->bitclk_rate == 843840000) {
		/* Selected factory DT: Sharp RSP61322 1080p60 at this bit rate. */
		timing->clk_zero = 0xe1;
		timing->clk_trail = 0x4b;
		timing->clk_prepare = 0x37;
		timing->hs_exit = 0xa9;
		timing->hs_zero = 0xab;
		timing->hs_prepare = 0x2a;
		timing->hs_trail = 0x4f;
		timing->hs_rqst = 0x3d;
		timing->ta_go = 3;
		timing->ta_sure = 0;
		timing->ta_get = 4;
		timing->shared_timings.clk_pre = 0x2f;
		timing->shared_timings.clk_post = 0x19;
		timing->shared_timings.clk_pre_inc_by_2 = false;
		dev_info(&phy->pdev->dev, "Libra PHY: selected factory 1080p60 timings\n");
	}

	dsi_20nm_phy_regulator_ctrl(phy, true);

	writel(libra ? 0x77 : 0xff, base + REG_DSI_20nm_PHY_STRENGTH_0);

	val = readl(base + REG_DSI_20nm_PHY_GLBL_TEST_CTRL);
	if (phy->id == DSI_1 && phy->usecase == MSM_DSI_PHY_STANDALONE)
		val |= DSI_20nm_PHY_GLBL_TEST_CTRL_BITCLK_HS_SEL;
	else
		val &= ~DSI_20nm_PHY_GLBL_TEST_CTRL_BITCLK_HS_SEL;
	writel(libra ? 0 : val, base + REG_DSI_20nm_PHY_GLBL_TEST_CTRL);

	for (i = 0; i < 4; i++) {
		writel((i >> 1) * 0x40, base + REG_DSI_20nm_PHY_LN_CFG_3(i));
		writel(0x01, base + REG_DSI_20nm_PHY_LN_TEST_STR_0(i));
		writel(0x46, base + REG_DSI_20nm_PHY_LN_TEST_STR_1(i));
		writel(0x02, base + REG_DSI_20nm_PHY_LN_CFG_0(i));
		writel(0xa0, base + REG_DSI_20nm_PHY_LN_CFG_1(i));
		writel(cfg_4[i], base + REG_DSI_20nm_PHY_LN_CFG_4(i));
		if (libra) {
			writel(0, base + REG_DSI_20nm_PHY_LN_CFG_2(i));
			writel(0, base + REG_DSI_20nm_PHY_LN_TEST_DATAPATH(i));
			writel(0, base + REG_DSI_20nm_PHY_LN_DEBUG_SEL(i));
		}
	}

	writel(0x80, base + REG_DSI_20nm_PHY_LNCK_CFG_3);
	writel(0x01, base + REG_DSI_20nm_PHY_LNCK_TEST_STR0);
	writel(0x46, base + REG_DSI_20nm_PHY_LNCK_TEST_STR1);
	writel(0x00, base + REG_DSI_20nm_PHY_LNCK_CFG_0);
	writel(0xa0, base + REG_DSI_20nm_PHY_LNCK_CFG_1);
	writel(0x00, base + REG_DSI_20nm_PHY_LNCK_CFG_2);
	writel(0x00, base + REG_DSI_20nm_PHY_LNCK_CFG_4);
	if (libra) {
		writel(0, base + REG_DSI_20nm_PHY_LNCK_TEST_DATAPATH);
		writel(0, base + REG_DSI_20nm_PHY_LNCK_DEBUG_SEL);
	}

	dsi_20nm_dphy_set_timing(phy, timing);

	writel(0x00, base + REG_DSI_20nm_PHY_CTRL_1);

	if (!libra)
		writel(0x06, base + REG_DSI_20nm_PHY_STRENGTH_1);

	/* make sure everything is written before enable */
	wmb();
	writel(0x7f, base + REG_DSI_20nm_PHY_CTRL_0);
	if (libra)
		writel(0x06, base + REG_DSI_20nm_PHY_STRENGTH_1);

	return 0;
}

static void dsi_20nm_phy_disable(struct msm_dsi_phy *phy)
{
	writel(0, phy->base + REG_DSI_20nm_PHY_CTRL_0);
	dsi_20nm_phy_regulator_ctrl(phy, false);
}

static const struct regulator_bulk_data dsi_phy_20nm_regulators[] = {
	{ .supply = "vddio", .init_load_uA = 100000 },	/* 1.8 V */
	{ .supply = "vcca", .init_load_uA = 10000 },	/* 1.0 V */
};

const struct msm_dsi_phy_cfg dsi_phy_20nm_cfgs = {
	.has_phy_regulator = true,
	.regulator_data = dsi_phy_20nm_regulators,
	.num_regulators = ARRAY_SIZE(dsi_phy_20nm_regulators),
	.ops = {
		.enable = dsi_20nm_phy_enable,
		.disable = dsi_20nm_phy_disable,
	},
	.io_start = { 0xfd998500, 0xfd9a0500 },
	.num_dsi_phy = 2,
};

/* MSM8992 uses PLL0 plus the auxiliary PLL1 bias block in 90-degree mode. */
const struct msm_dsi_phy_cfg dsi_phy_20nm_8992_cfgs = {
	.has_phy_regulator = true,
	.regulator_data = dsi_phy_20nm_regulators,
	.num_regulators = ARRAY_SIZE(dsi_phy_20nm_regulators),
	.ops = {
		.pll_init = dsi_pll_20nm_8992_init,
		.enable = dsi_20nm_phy_enable,
		.disable = dsi_20nm_phy_disable,
	},
	.min_pll_rate = 1000000000,
	.max_pll_rate = 2000000000,
	.io_start = { 0xfd994500 },
	.num_dsi_phy = 1,
};
