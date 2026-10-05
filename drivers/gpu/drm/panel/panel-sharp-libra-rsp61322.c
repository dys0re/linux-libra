// SPDX-License-Identifier: GPL-2.0-only
/* Xiaomi Mi 4C Sharp RSP61322 video-mode panel.
 * Sequences from the downstream Xiaomi panel device tree.
 * Copyright (c) 2015, The Linux Foundation.
 * Copyright (C) 2016 XiaoMi, Inc.
 */
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/iopoll.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/regulator/consumer.h>
#include <drm/drm_mipi_dsi.h>
#include <drm/drm_modes.h>
#include <drm/drm_panel.h>
#include <video/mipi_display.h>

struct libra_panel {
	struct drm_panel panel;
	struct mipi_dsi_device *dsi;
	struct regulator_bulk_data supplies[2];
	struct gpio_desc *reset;
	struct gpio_desc *enable;
	struct mutex lock;
	bool prepared;
};

static bool read_power_mode;
module_param(read_power_mode, bool, 0400);
MODULE_PARM_DESC(read_power_mode,
		"Expose explicit diagnostics for the prepared panel");

struct libra_panel_cmd {
	u8 type;
	u8 delay_ms;
	u8 len;
	u8 data[31];
};

static const struct libra_panel_cmd libra_on[] = {
	{ 0x23, 0, 2, { 0xb0, 0x00 } },
	{ 0x23, 0, 2, { 0xd6, 0x01 } },
	{ 0x29, 0, 25, { 0xce, 0x3d, 0x40, 0x48, 0x56, 0x67, 0x78, 0x88,
		0x98, 0xa7, 0xb5, 0xc3, 0xd1, 0xde, 0xe9, 0xf2, 0xfa, 0xff,
		0x01, 0x5f, 0x04, 0x04, 0x00, 0x00, 0x00 } },
	{ 0x29, 0, 31, { 0xc7, 0x0b, 0x18, 0x20, 0x2b, 0x3a, 0x48, 0x51,
		0x60, 0x45, 0x4d, 0x58, 0x65, 0x71, 0x73, 0x74, 0x09, 0x16,
		0x1e, 0x29, 0x38, 0x48, 0x51, 0x60, 0x45, 0x4d, 0x58, 0x65,
		0x71, 0x75, 0x76 } },
	{ 0x29, 0, 20, { 0xc8, 0x01, 0x00, 0x09, 0x02, 0xfd, 0xcf, 0x00,
		0x00, 0x05, 0xfe, 0x02, 0xfc, 0x00, 0x00, 0x0c, 0xfe, 0xf4,
		0xe8, 0x00 } },
	{ 0x29, 0, 4, { 0xc3, 0x01, 0x00, 0x0a } },
	{ 0x29, 0, 6, { 0xec, 0x04, 0x10, 0x32, 0x00, 0x00 } },
	{ 0x23, 0, 2, { 0xb0, 0x03 } },
	{ 0x15, 0, 2, { 0x34, 0x00 } },
	{ 0x39, 0, 2, { 0x51, 0xff } },
	{ 0x15, 0, 2, { 0x53, 0x24 } },
	{ 0x15, 0, 2, { 0x55, 0x01 } },
	/* The vendor deliberately sends display-on before sleep-out. */
	{ 0x05, 20, 1, { 0x29 } },
	{ 0x05, 50, 1, { 0x11 } },
};

static const struct libra_panel_cmd libra_off[] = {
	{ 0x05, 29, 1, { 0x28 } },
	{ 0x05, 120, 1, { 0x10 } },
};

static int libra_panel_commands(struct libra_panel *ctx,
			       const struct libra_panel_cmd *cmds, size_t count,
			       bool low_power)
{
	size_t i;
	ssize_t ret;
	const struct mipi_dsi_host_ops *ops = ctx->dsi->host->ops;

	if (!ops || !ops->transfer)
		return -EOPNOTSUPP;

	for (i = 0; i < count; i++) {
		struct mipi_dsi_msg msg = {
			.channel = ctx->dsi->channel,
			.type = cmds[i].type,
			.flags = low_power ? MIPI_DSI_MSG_USE_LPM : 0,
			.tx_len = cmds[i].len,
			.tx_buf = cmds[i].data,
		};

		/* Preserve the original packet type (including two-byte long DCS). */
		ret = ops->transfer(ctx->dsi->host, &msg);
		if (ret < 0)
			return ret;
		/* Older MSM hosts return the padded DMA packet length. */
		if (ret < cmds[i].len)
			return -EIO;
		if (cmds[i].delay_ms)
			msleep(cmds[i].delay_ms);
	}
	return 0;
}

static int libra_panel_read_power_mode(struct libra_panel *ctx, u8 *mode,
				       const char *phase)
{
	const struct mipi_dsi_host_ops *ops = ctx->dsi->host->ops;
	u8 command = MIPI_DCS_GET_POWER_MODE;
	struct mipi_dsi_msg msg = {
		.channel = ctx->dsi->channel,
		.type = MIPI_DSI_DCS_READ,
		.flags = MIPI_DSI_MSG_USE_LPM,
		.tx_len = 1,
		.tx_buf = &command,
		.rx_len = 1,
		.rx_buf = mode,
	};
	ssize_t ret;

	*mode = 0;
	if (!ops || !ops->transfer)
		ret = -EOPNOTSUPP;
	else
		ret = ops->transfer(ctx->dsi->host, &msg);
	if (ret != 1) {
		dev_warn(&ctx->dsi->dev,
			 "panel power-mode read failed: phase=%s ret=%zd (expected 1 byte)\n",
			 phase, ret);
		return ret < 0 ? ret : -EPROTO;
	}
	dev_info(&ctx->dsi->dev,
		 "panel power-mode: phase=%s raw=%#04x display_on=%u sleep_out=%u normal=%u\n",
		 phase, *mode, !!(*mode & MIPI_DSI_DCS_POWER_MODE_DISPLAY),
		 !!(*mode & MIPI_DSI_DCS_POWER_MODE_SLEEP),
		 !!(*mode & MIPI_DSI_DCS_POWER_MODE_NORMAL));
	return 0;
}

static int libra_panel_bias_ready(struct libra_panel *ctx)
{
	unsigned int flags, i;
	int ret;

	for (i = 0; i < ARRAY_SIZE(ctx->supplies); i++) {
		ret = regulator_is_enabled(ctx->supplies[i].consumer);
		if (ret <= 0)
			return ret;
		ret = regulator_get_error_flags(ctx->supplies[i].consumer, &flags);
		if (ret)
			return ret;
		if (flags & ~REGULATOR_ERROR_UNDER_VOLTAGE)
			return -EIO;
		if (flags & REGULATOR_ERROR_UNDER_VOLTAGE)
			return 0;
	}
	return 1;
}

static int libra_panel_prepare(struct drm_panel *panel)
{
	struct libra_panel *ctx = container_of(panel, struct libra_panel, panel);
	int ret, ready;

	mutex_lock(&ctx->lock);
	ret = regulator_bulk_enable(ARRAY_SIZE(ctx->supplies), ctx->supplies);
	if (ret)
		goto unlock;
	/* Vendor cold init checks both VREG_OK bits before panel reset. */
	ret = read_poll_timeout(libra_panel_bias_ready, ready, ready != 0,
				1000, 100000, false, ctx);
	if (!ret && ready < 0)
		ret = ready;
	if (ret) {
		dev_err(&ctx->dsi->dev, "panel bias output not ready: %d\n", ret);
		goto supplies_off;
	}
	ret = gpiod_direction_output(ctx->enable, 1);
	if (ret)
		goto supplies_off;
	/* Active-low reset: original electrical sequence is high/low/high. */
	ret = gpiod_direction_output(ctx->reset, 0);
	if (ret)
		goto disable_panel;
	usleep_range(5000, 6000);
	gpiod_set_value_cansleep(ctx->reset, 1);
	usleep_range(10000, 11000);
	gpiod_set_value_cansleep(ctx->reset, 0);
	usleep_range(10000, 11000);
	ret = libra_panel_commands(ctx, libra_on, ARRAY_SIZE(libra_on), true);
	if (!ret) {
		ctx->prepared = true;
		goto unlock;
	}
	gpiod_set_value_cansleep(ctx->reset, 1);
disable_panel:
	gpiod_set_value_cansleep(ctx->enable, 0);
supplies_off:
	regulator_bulk_disable(ARRAY_SIZE(ctx->supplies), ctx->supplies);
unlock:
	mutex_unlock(&ctx->lock);
	return ret;
}

static int libra_panel_unprepare(struct drm_panel *panel)
{
	struct libra_panel *ctx = container_of(panel, struct libra_panel, panel);
	int ret;

	mutex_lock(&ctx->lock);
	ctx->prepared = false;
	ret = libra_panel_commands(ctx, libra_off, ARRAY_SIZE(libra_off), false);
	gpiod_set_value_cansleep(ctx->reset, 1);
	gpiod_set_value_cansleep(ctx->enable, 0);
	regulator_bulk_disable(ARRAY_SIZE(ctx->supplies), ctx->supplies);
	mutex_unlock(&ctx->lock);
	return ret;
}

static ssize_t power_mode_show(struct device *dev,
			       struct device_attribute *attr, char *buf)
{
	struct libra_panel *ctx = dev_get_drvdata(dev);
	u8 mode;
	int ret;

	mutex_lock(&ctx->lock);
	if (!ctx->prepared) {
		ret = -EPIPE;
		goto out;
	}
	ret = libra_panel_read_power_mode(ctx, &mode, "active");
	if (ret)
		goto out;
	if (!(mode & MIPI_DSI_DCS_POWER_MODE_DISPLAY) ||
	    !(mode & MIPI_DSI_DCS_POWER_MODE_SLEEP))
		dev_warn(dev, "panel power-mode not ready after video start\n");
	ret = sysfs_emit(buf, "raw=%#04x display_on=%u sleep_out=%u normal=%u\n",
			 mode, !!(mode & MIPI_DSI_DCS_POWER_MODE_DISPLAY),
			 !!(mode & MIPI_DSI_DCS_POWER_MODE_SLEEP),
			 !!(mode & MIPI_DSI_DCS_POWER_MODE_NORMAL));
out:
	mutex_unlock(&ctx->lock);
	return ret;
}
static DEVICE_ATTR_RO(power_mode);

static ssize_t wake_test_store(struct device *dev,
			       struct device_attribute *attr,
			       const char *buf, size_t count)
{
	struct libra_panel *ctx = dev_get_drvdata(dev);
	const struct libra_panel_cmd wake = {
		.type = MIPI_DSI_DCS_SHORT_WRITE,
		.delay_ms = 120,
		.len = 1,
		.data = { MIPI_DCS_EXIT_SLEEP_MODE },
	};
	bool lp;
	u8 mode;
	int ret;

	if (sysfs_streq(buf, "lp"))
		lp = true;
	else if (sysfs_streq(buf, "hs"))
		lp = false;
	else
		return -EINVAL;

	mutex_lock(&ctx->lock);
	if (!ctx->prepared) {
		ret = -EPIPE;
		goto out;
	}
	ret = libra_panel_read_power_mode(ctx, &mode, "wake-before");
	if (ret)
		goto out;
	if (mode & MIPI_DSI_DCS_POWER_MODE_SLEEP) {
		dev_info(dev, "panel wake test: already awake, no command sent\n");
		goto out;
	}
	dev_info(dev, "panel wake test: mode=%s command=0x11 wait=120ms\n",
		 lp ? "lp" : "hs");
	/* One explicit standard Sleep Out, with no automatic retries. */
	ret = libra_panel_commands(ctx, &wake, 1, lp);
	if (ret)
		goto out;
	ret = libra_panel_read_power_mode(ctx, &mode, lp ? "wake-lp" : "wake-hs");
	if (!ret && !(mode & MIPI_DSI_DCS_POWER_MODE_SLEEP)) {
		dev_warn(dev, "panel wake test: mode=%s panel remains asleep\n",
			 lp ? "lp" : "hs");
		ret = -EAGAIN;
	}
out:
	mutex_unlock(&ctx->lock);
	if (ret)
		return ret;
	return count;
}
static DEVICE_ATTR_WO(wake_test);

static ssize_t identity_show(struct device *dev,
			    struct device_attribute *attr, char *buf)
{
	struct libra_panel *ctx = dev_get_drvdata(dev);
	const struct mipi_dsi_host_ops *ops = ctx->dsi->host->ops;
	u8 id[3] = { 0 }, command;
	struct mipi_dsi_msg msg = {
		.channel = ctx->dsi->channel,
		.type = MIPI_DSI_DCS_READ,
		.flags = MIPI_DSI_MSG_USE_LPM,
		.tx_len = 1,
		.tx_buf = &command,
		.rx_len = 1,
	};
	ssize_t ret;
	unsigned int i;

	mutex_lock(&ctx->lock);
	if (!ctx->prepared) {
		ret = -EPIPE;
		goto out;
	}
	if (!ops || !ops->transfer) {
		ret = -EOPNOTSUPP;
		goto out;
	}
	/* Raw ID registers only; do not infer a panel profile from unknown IDs. */
	for (i = 0; i < ARRAY_SIZE(id); i++) {
		command = 0xda + i;
		msg.rx_buf = &id[i];
		ret = ops->transfer(ctx->dsi->host, &msg);
		if (ret != 1) {
			ret = ret < 0 ? ret : -EPROTO;
			goto out;
		}
	}
	ret = sysfs_emit(buf, "id_da=%#04x id_db=%#04x id_dc=%#04x\n",
			 id[0], id[1], id[2]);
out:
	mutex_unlock(&ctx->lock);
	return ret;
}
static DEVICE_ATTR_RO(identity);

static umode_t libra_panel_diag_visible(struct kobject *kobj,
				       struct attribute *attr, int index)
{
	return read_power_mode ? attr->mode : 0;
}

static struct attribute *libra_panel_diag_attrs[] = {
	&dev_attr_power_mode.attr, &dev_attr_wake_test.attr,
	&dev_attr_identity.attr, NULL,
};
static const struct attribute_group libra_panel_diag_group = {
	.attrs = libra_panel_diag_attrs,
	.is_visible = libra_panel_diag_visible,
};
static const struct attribute_group *libra_panel_diag_groups[] = {
	&libra_panel_diag_group, NULL,
};

static int libra_panel_get_modes(struct drm_panel *panel,
				 struct drm_connector *connector)
{
	static const struct drm_display_mode timing = {
		.clock = (1080 + 72 + 10 + 50) * (1920 + 7 + 2 + 5) * 60 / 1000,
		.hdisplay = 1080,
		.hsync_start = 1080 + 72,
		.hsync_end = 1080 + 72 + 10,
		.htotal = 1080 + 72 + 10 + 50,
		.vdisplay = 1920,
		.vsync_start = 1920 + 7,
		.vsync_end = 1920 + 7 + 2,
		.vtotal = 1920 + 7 + 2 + 5,
		.width_mm = 61,
		.height_mm = 109,
	};
	struct drm_display_mode *mode;

	mode = drm_mode_duplicate(connector->dev, &timing);
	if (!mode)
		return -ENOMEM;
	drm_mode_set_name(mode);
	mode->type = DRM_MODE_TYPE_DRIVER | DRM_MODE_TYPE_PREFERRED;
	drm_mode_probed_add(connector, mode);
	connector->display_info.width_mm = timing.width_mm;
	connector->display_info.height_mm = timing.height_mm;
	return 1;
}

static const struct drm_panel_funcs libra_panel_funcs = {
	.prepare = libra_panel_prepare,
	.unprepare = libra_panel_unprepare,
	.get_modes = libra_panel_get_modes,
};

static int libra_panel_probe(struct mipi_dsi_device *dsi)
{
	struct libra_panel *ctx;
	int ret;

	ctx = devm_kzalloc(&dsi->dev, sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	ctx->dsi = dsi;
	mutex_init(&ctx->lock);
	ctx->supplies[0].supply = "avdd";
	ctx->supplies[1].supply = "avee";
	ret = devm_regulator_bulk_get(&dsi->dev, ARRAY_SIZE(ctx->supplies), ctx->supplies);
	if (ret)
		return ret;
	ctx->reset = devm_gpiod_get(&dsi->dev, "reset", GPIOD_ASIS);
	if (IS_ERR(ctx->reset))
		return dev_err_probe(&dsi->dev, PTR_ERR(ctx->reset), "Missing reset GPIO\n");
	ctx->enable = devm_gpiod_get(&dsi->dev, "enable", GPIOD_ASIS);
	if (IS_ERR(ctx->enable))
		return dev_err_probe(&dsi->dev, PTR_ERR(ctx->enable), "Missing enable GPIO\n");

	dsi->lanes = 4;
	dsi->format = MIPI_DSI_FMT_RGB888;
	/* Vendor requires LP11 reset/init and does not force the clock lane HS. */
	dsi->mode_flags = MIPI_DSI_MODE_VIDEO | MIPI_DSI_MODE_VIDEO_BURST |
		MIPI_DSI_MODE_NO_EOT_PACKET | MIPI_DSI_CLOCK_NON_CONTINUOUS;
	drm_panel_init(&ctx->panel, &dsi->dev, &libra_panel_funcs, DRM_MODE_CONNECTOR_DSI);
	ctx->panel.prepare_prev_first = true;
	ret = drm_panel_of_backlight(&ctx->panel);
	if (ret)
		return ret;
	drm_panel_add(&ctx->panel);
	mipi_dsi_set_drvdata(dsi, ctx);
	ret = mipi_dsi_attach(dsi);
	if (ret)
		drm_panel_remove(&ctx->panel);
	return ret;
}

static void libra_panel_remove(struct mipi_dsi_device *dsi)
{
	struct libra_panel *ctx = mipi_dsi_get_drvdata(dsi);

	drm_panel_disable(&ctx->panel);
	drm_panel_unprepare(&ctx->panel);
	mipi_dsi_detach(dsi);
	drm_panel_remove(&ctx->panel);
}

static const struct of_device_id libra_panel_match[] = {
	{ .compatible = "sharp,libra-rsp61322" },
	{ }
};
MODULE_DEVICE_TABLE(of, libra_panel_match);

static struct mipi_dsi_driver libra_panel_driver = {
	.probe = libra_panel_probe,
	.remove = libra_panel_remove,
	.driver = {
		.name = "panel-sharp-libra-rsp61322",
		.of_match_table = libra_panel_match,
		.dev_groups = libra_panel_diag_groups,
	},
};
module_mipi_dsi_driver(libra_panel_driver);
MODULE_DESCRIPTION("Xiaomi Mi 4C Sharp RSP61322 video-mode panel");
MODULE_LICENSE("GPL");
