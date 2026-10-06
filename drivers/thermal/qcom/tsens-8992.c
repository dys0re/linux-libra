// SPDX-License-Identifier: GPL-2.0-only
/* MSM8992 calibration layout from Qualcomm's msm8974-tsens.c. */
#include <linux/bitfield.h>
#include "tsens.h"

static unsigned int msm8992_hw_ids[] = {
	0, 1, 2, 3, 4, 5, 7, 9, 10, 11, 12, 13, 14,
};

static int calibrate_8992(struct tsens_priv *priv)
{
	u32 *data, *sel, base1, base2, mode, p1[13], p2[13], delta[16];
	bool backup;
	int i;

	sel = (u32 *)qfprom_read(priv->dev, "calib-select");
	if (IS_ERR(sel))
		return PTR_ERR(sel);
	backup = FIELD_GET(GENMASK(31, 29), sel[0]) == 3;
	kfree(sel);
	data = (u32 *)qfprom_read(priv->dev, backup ? "calib-backup" : "calib");
	if (IS_ERR(data))
		return PTR_ERR(data);

	if (backup) {
		/* Backup cell starts at QFPROM offset 0x1c0. */
		u32 a = data[0], b = data[1], c = data[3];
		u32 d = data[(0x440 - 0x1c0) / 4];

		mode = data[(0x444 - 0x1c0) / 4] & 7;
		base1 = FIELD_GET(GENMASK(30, 21), a);
		/* Bit 0 lives in row 1; bits 1--9 live in row 2. */
		base2 = (a >> 31) | ((b & 0x1ff) << 1);
		for (i = 0; i < 5; i++)
			delta[i] = (b >> (9 + i * 4)) & 0xf;
		delta[5] = ((b >> 29) & 7) | (((c >> 23) & 1) << 3);
		delta[6] = (c >> 24) & 0xf;
		delta[7] = c >> 28;
		for (i = 8; i < 16; i++)
			delta[i] = (d >> ((i - 8) * 4)) & 0xf;
		for (i = 0; i < priv->num_sensors; i++)
			p1[i] = base1 + delta[msm8992_hw_ids[i]];
	} else {
		mode = FIELD_GET(GENMASK(22, 20), data[2]);
		base1 = FIELD_GET(GENMASK(9, 0), data[0]);
		base2 = FIELD_GET(GENMASK(19, 10), data[0]);
		/* Primary offsets are packed by software index, unlike backup. */
		for (i = 0; i < 3; i++)
			p1[i] = base1 + ((data[0] >> (20 + i * 4)) & 0xf);
		for (i = 3; i < 11; i++)
			p1[i] = base1 + ((data[1] >> ((i - 3) * 4)) & 0xf);
		for (i = 11; i < 13; i++)
			p1[i] = base1 + ((data[2] >> ((i - 11) * 4)) & 0xf);
	}
	kfree(data);
	dev_info(priv->dev, "MSM8992 TSENS: mode=%u base1=%u base2=%u bank=%s\n",
		 mode, base1, base2, backup ? "backup" : "primary");
	/* Do not publish guessed temperatures when the fuse mode is unknown. */
	if (mode != TWO_PT_CALIB || base2 <= base1)
		return -EINVAL;
	for (i = 0; i < priv->num_sensors; i++)
		p2[i] = p1[i] + base2 - base1;
	compute_intercept_slope(priv, p1, p2, TWO_PT_CALIB);
	dev_info(priv->dev, "MSM8992: 13 sensors, %s two-point calibration\n",
		 backup ? "backup" : "primary");
	return 0;
}

/* Type-2 TSENS uses the 1xxx control layout, unlike legacy type-0. */
static struct tsens_features msm8992_feat = {
	.ver_major = VER_0_1,
	.adc = 1,
	.srot_split = 1,
	.max_sensors = 16,
	.trip_min_temp = -40000,
	.trip_max_temp = 120000,
};

static const struct reg_field msm8992_fields[MAX_REGFIELDS] = {
	[TSENS_EN] = REG_FIELD(0x04, 0, 0),
	[TSENS_SW_RST] = REG_FIELD(0x04, 1, 1),
	[SENSOR_EN] = REG_FIELD(0x04, 3, 18),
	[INT_EN] = REG_FIELD(0, 0, 0),
	[TRDY] = REG_FIELD(0x84, 0, 0),
	REG_FIELD_FOR_EACH_SENSOR16(LOW_THRESH, 0x04, 0, 9),
	REG_FIELD_FOR_EACH_SENSOR16(UP_THRESH, 0x04, 10, 19),
	REG_FIELD_FOR_EACH_SENSOR16(LOW_INT_CLEAR, 0x04, 20, 20),
	REG_FIELD_FOR_EACH_SENSOR16(UP_INT_CLEAR, 0x04, 21, 21),
	REG_FIELD_FOR_EACH_SENSOR16(LAST_TEMP, 0x44, 0, 9),
	REG_FIELD_FOR_EACH_SENSOR16(VALID, 0x44, 14, 14),
	REG_FIELD_FOR_EACH_SENSOR16(LOWER_STATUS, 0x44, 11, 11),
	REG_FIELD_FOR_EACH_SENSOR16(UPPER_STATUS, 0x44, 12, 12),
	REG_FIELD_FOR_EACH_SENSOR16(LOW_INT_STATUS, 0x44, 11, 11),
	REG_FIELD_FOR_EACH_SENSOR16(UP_INT_STATUS, 0x44, 12, 12),
};

static const struct tsens_ops msm8992_ops = {
	.init = init_common,
	.calibrate = calibrate_8992,
	.get_temp = get_temp_tsens_valid,
};

struct tsens_plat_data data_8992 = {
	.num_sensors = ARRAY_SIZE(msm8992_hw_ids),
	.hw_ids = msm8992_hw_ids,
	.feat = &msm8992_feat,
	.fields = msm8992_fields,
	.ops = &msm8992_ops,
};
