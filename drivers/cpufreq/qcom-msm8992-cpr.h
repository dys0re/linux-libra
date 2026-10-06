/* SPDX-License-Identifier: GPL-2.0-only */
/* MSM8992 factory CPR open-loop voltage calculation; fuse data is read-only. */
#ifndef QCOM_MSM8992_CPR_H
#define QCOM_MSM8992_CPR_H

#define MSM8992_MAX_CORNERS 15
struct msm8992_cpr_plan {
	unsigned int count;
	unsigned int speedbin;
	unsigned int revision;
	bool backup;
	unsigned long hz[MSM8992_MAX_CORNERS];
	unsigned int uv[MSM8992_MAX_CORNERS];
};

/* qcom,cpr-fuse-init-voltage */
static const u32 cpr0_fuse_init[] = {
	139, 46, 6, 0, 139, 46, 6, 0,
	139, 40, 6, 0, 139, 52, 6, 0,
};
/* qcom,cpr-fuse-redun-init-voltage */
static const u32 cpr0_backup_init[] = {
	1000, 41, 6, 0, 1000, 41, 6, 0,
	1000, 47, 6, 0, 1000, 32, 6, 0,
};
/* qcom,fuse-remap-source */
static const u32 cpr0_remap[] = {
	56, 21, 41, 0, 136, 62, 12, 0,
};
/* qcom,cpr-init-voltage-ref */
static const u32 cpr0_ref[] = {
	900000, 900000, 1000000, 1230000,
};
/* qcom,cpr-init-voltage-adjustment */
static const int cpr0_adjust[] = {
	0, 0, 0, 0, 0, -15000, -35000, 35000,
	0, -15000, -35000, 35000, 0, -15000, -25000, -15000,
	0, -15000, -25000, -60000, 0, 0, 0, 0,
	0, -15000, -35000, 95000, 0, -15000, -35000, 95000,
	0, -15000, -25000, 45000, 0, -15000, -25000, 0,
};
/* qcom,cpr-fuse-version-map */
static const u32 cpr0_version_map[] = {
	0, 0xffffffff, 0, 0, 0, 0, 0, 0,
	0xffffffff, 1, 0, 0, 0, 0, 0, 0xffffffff,
	2, 0, 0, 0, 0, 0, 0xffffffff, 3,
	0, 0, 0, 0, 0, 0xffffffff, 4, 0,
	0, 0, 0, 1, 0xffffffff, 0, 0, 0,
	0, 0, 1, 0xffffffff, 1, 0, 0, 0,
	0, 1, 0xffffffff, 2, 0, 0, 0, 0,
	1, 0xffffffff, 3, 0, 0, 0, 0, 1,
	0xffffffff, 4, 0, 0, 0, 0,
};
/* qcom,cpr-voltage-floor */
static const u32 cpr0_fuse_floor[] = {
	640000, 700000, 800000, 850000,
};
/* qcom,cpr-voltage-ceiling */
static const u32 cpr0_fuse_ceiling[] = {
	900000, 900000, 1000000, 1180000,
};
/* qcom,cpr-voltage-floor-override */
static const u32 cpr0_floor[] = {
	0xffffffff, 0, 640000, 655000, 700000, 735000, 800000, 835000,
	850000, 875000, 950000, 1000000,
};
/* qcom,cpr-voltage-ceiling-override */
static const u32 cpr0_ceiling[] = {
	0xffffffff, 0, 800000, 800000, 900000, 900000, 1000000, 1000000,
	1115000, 1115000, 1180000, 1180000,
};
/* qcom,cpr-corner-map */
static const u32 cpr0_map[] = {
	1, 1, 2, 2, 3, 3, 4, 4,
	4, 4,
};
/* qcom,cpr-corner-frequency-map */
static const u32 cpr0_freq_map[] = {
	1, 300000000, 2, 384000000, 3, 460800000, 4, 600000000,
	5, 672000000, 6, 787200000, 7, 864000000, 8, 960000000,
	9, 1248000000, 10, 1440000000,
};
/* qcom,cpr-speed-bin-max-corners */
static const u32 cpr0_max_corners[] = {
	0, 0, 2, 4, 6, 9, 1, 0,
	2, 4, 6, 10,
};
/* qcom,cpr-voltage-scaling-factor-max */
static const u32 cpr0_scaling[] = {
	0, 0, 2000, 2000,
};
/* qcom,cpr-fuse-ro-sel */
static const u32 cpr0_ro[] = {
	98, 98, 95, 101,
};
/* qcom,cpr-fuse-redun-ro-sel */
static const u32 cpr0_backup_ro[] = {
	38, 38, 38, 38,
};
/* qcom,cpr-fuse-init-voltage */
static const u32 cpr1_fuse_init[] = {
	140, 48, 6, 0, 140, 48, 6, 0,
	140, 42, 6, 0, 140, 54, 6, 0,
};
/* qcom,cpr-fuse-redun-init-voltage */
static const u32 cpr1_backup_init[] = {
	1000, 33, 6, 0, 1000, 33, 6, 0,
	1000, 39, 6, 0, 1000, 24, 6, 0,
};
/* qcom,fuse-remap-source */
static const u32 cpr1_remap[] = {
	56, 62, 2, 0, 57, 55, 9, 0,
	136, 0, 22, 0, 137, 10, 12, 0,
};
/* qcom,cpr-init-voltage-ref */
static const u32 cpr1_ref[] = {
	900000, 900000, 1000000, 1230000,
};
/* qcom,cpr-init-voltage-adjustment */
static const int cpr1_adjust[] = {
	0, 0, 0, 0, 0, 0, -25000, -25000,
	0, 0, 30000, -5000, 30000, 30000, -20000, -20000,
	30000, 30000, -20000, -20000,
};
/* qcom,cpr-fuse-version-map */
static const u32 cpr1_version_map[] = {
	0xffffffff, 0xffffffff, 0, 4, 4, 4, 4, 0xffffffff,
	0xffffffff, 1, 4, 4, 4, 4, 0xffffffff, 0xffffffff,
	2, 4, 4, 4, 4, 0xffffffff, 0xffffffff, 3,
	2, 2, 2, 2, 0xffffffff, 0xffffffff, 4, 2,
	2, 2, 2,
};
/* qcom,cpr-voltage-floor */
static const u32 cpr1_fuse_floor[] = {
	640000, 640000, 745000, 850000,
};
/* qcom,cpr-voltage-ceiling */
static const u32 cpr1_fuse_ceiling[] = {
	900000, 900000, 1000000, 1180000,
};
/* qcom,cpr-voltage-floor-override */
static const u32 cpr1_floor[] = {
	0xffffffff, 0, 640000, 640000, 665000, 690000, 735000, 745000,
	770000, 785000, 850000, 860000, 880000, 900000, 920000, 935000,
	1000000,
};
/* qcom,cpr-voltage-ceiling-override */
static const u32 cpr1_ceiling[] = {
	0xffffffff, 0, 900000, 900000, 900000, 900000, 900000, 1000000,
	1000000, 1000000, 1115000, 1115000, 1115000, 1115000, 1115000, 1115000,
	1180000,
};
/* qcom,cpr-corner-map */
static const u32 cpr1_map[] = {
	1, 2, 2, 2, 2, 3, 3, 3,
	4, 4, 4, 4, 4, 4, 4,
};
/* qcom,cpr-corner-frequency-map */
static const u32 cpr1_freq_map[] = {
	1, 300000000, 2, 300000000, 3, 384000000, 4, 480000000,
	5, 633600000, 6, 768000000, 7, 864000000, 8, 960000000,
	9, 1248000000, 10, 1344000000, 11, 1440000000, 12, 1536000000,
	13, 1632000000, 14, 1689600000, 15, 1824000000,
};
/* qcom,cpr-speed-bin-max-corners */
static const u32 cpr1_max_corners[] = {
	0xffffffff, 0, 1, 5, 8, 15,
};
/* qcom,cpr-voltage-scaling-factor-max */
static const u32 cpr1_scaling[] = {
	0, 0, 2000, 2000,
};
/* qcom,cpr-fuse-ro-sel */
static const u32 cpr1_ro[] = {
	36, 36, 33, 39,
};
/* qcom,cpr-fuse-redun-ro-sel */
static const u32 cpr1_backup_ro[] = {
	30, 30, 30, 30,
};

static const u32 cci0_map[] = { 384000, 134400, 600000, 300000, 787200, 384000, 864000, 556800, 960000, 729600, 1440000, 787200 };
static const u32 cci1_map[] = { 384000, 134400, 480000, 300000, 633600, 384000, 768000, 556800, 960000, 600000, 1440000, 729600, 1824000, 787200 };

static u64 msm8992_fuse_bits(const u8 *data, unsigned int row,
			    unsigned int bit, unsigned int width)
{
	u64 value = 0;
	unsigned int i, pos = row * 64 + bit;

	for (i = 0; i < width; i++)
		value |= (u64)((data[(pos + i) / 8] >> ((pos + i) % 8)) & 1) << i;
	return value;
}

static int msm8992_cpr_calculate(const u8 *data, unsigned int cluster,
				unsigned int speedbin, struct msm8992_cpr_plan *plan)
{
	const u32 *init = cluster ? cpr1_fuse_init : cpr0_fuse_init;
	const u32 *backup_init = cluster ? cpr1_backup_init : cpr0_backup_init;
	const u32 *remap = cluster ? cpr1_remap : cpr0_remap;
	const u32 *ref = cluster ? cpr1_ref : cpr0_ref;
	const int *adjust = cluster ? cpr1_adjust : cpr0_adjust;
	const u32 *versions = cluster ? cpr1_version_map : cpr0_version_map;
	const u32 *floor = cluster ? cpr1_floor : cpr0_floor;
	const u32 *ceiling = cluster ? cpr1_ceiling : cpr0_ceiling;
	const u32 *fuse_floor = cluster ? cpr1_fuse_floor : cpr0_fuse_floor;
	const u32 *fuse_ceiling = cluster ? cpr1_fuse_ceiling : cpr0_fuse_ceiling;
	const u32 *map = cluster ? cpr1_map : cpr0_map;
	const u32 *freq = cluster ? cpr1_freq_map : cpr0_freq_map;
	const u32 *scale = cluster ? cpr1_scaling : cpr0_scaling;
	const u32 *ro = cluster ? cpr1_ro : cpr0_ro;
	const u32 *backup_ro = cluster ? cpr1_backup_ro : cpr0_backup_ro;
	unsigned int nr_remap = cluster ? 4 : 2, nr_versions = cluster ? 5 : 10;
	const u32 *max_corner;
	unsigned int count = cluster ? 15 : 10;
	unsigned int ro_sel[4], revision, pos = 0;
	int volts[4], match = -1;
	u64 remapped = 0;
	bool backup;
	unsigned int i, j;

	if (!cluster && speedbin > 1)
		return -EINVAL;
	max_corner = cluster ? cpr1_max_corners + 2 : cpr0_max_corners + speedbin * 6 + 2;
	backup = msm8992_fuse_bits(data, 62, 48, 3) == 1;
	revision = msm8992_fuse_bits(data, 137, 34, 3);
	if (backup)
		for (i = 0; i < nr_remap; i++) {
			remapped |= msm8992_fuse_bits(data, remap[i * 4],
				remap[i * 4 + 1], remap[i * 4 + 2]) << pos;
			pos += remap[i * 4 + 2];
		}
	for (i = 0; i < 4; i++)
		ro_sel[i] = backup ? (remapped >> backup_ro[i]) & 7 :
			msm8992_fuse_bits(data, cluster ? 140 : 138, ro[i], 3);
	/* Match all the factory tuple fields, including RO selection. */
	for (i = 0; i < nr_versions; i++) {
		const u32 *tuple = &versions[i * 7];

		if ((tuple[0] != U32_MAX && tuple[0] != speedbin) ||
		    (tuple[1] != U32_MAX && tuple[1] != 0) || tuple[2] != revision)
			continue;
		for (j = 0; j < 4; j++)
			if (tuple[j + 3] != U32_MAX && tuple[j + 3] != ro_sel[j])
				break;
		if (j == 4) {
			match = i;
			break;
		}
	}
	for (i = 0; i < 4; i++) {
		u32 value = backup ? (remapped >> backup_init[i * 4 + 1]) & 63 :
			msm8992_fuse_bits(data, init[i * 4], init[i * 4 + 1], 6);

		volts[i] = ref[i] + ((value & 32) ? -1 : 1) * (value & 31) * 10000;
		if (match >= 0)
			volts[i] += adjust[match * 4 + i];
		volts[i] = clamp(volts[i], (int)fuse_floor[i], (int)fuse_ceiling[i]);
	}
	for (i = 0; i < count; i++) {
		unsigned int fc = map[i] - 1;
		int uv = volts[fc];

		plan->hz[i] = freq[i * 2 + 1];
		/* Same capped interpolation and 5 mV rounding as factory CPR. */
		if (fc && i + 1 > max_corner[fc - 1] && i + 1 < max_corner[fc]) {
			u64 hi = freq[(max_corner[fc] - 1) * 2 + 1];
			u64 lo = freq[(max_corner[fc - 1] - 1) * 2 + 1];

			if (hi > lo && volts[fc] > volts[fc - 1]) {
				u64 diff = hi - plan->hz[i];
				u64 delta = div_u64(diff * (volts[fc] - volts[fc - 1]), hi - lo);
				u64 limit = div_u64(diff * scale[fc], 1000000);

				uv = volts[fc] - min(delta, limit);
				uv = DIV_ROUND_UP(uv, 5000) * 5000;
			}
		}
		plan->uv[i] = clamp(uv, (int)floor[i + 2], (int)ceiling[i + 2]);
	}
	plan->count = cluster ? 15 : (speedbin ? 10 : 9);
	plan->speedbin = speedbin;
	plan->revision = revision;
	plan->backup = backup;
	return 0;
}
#endif
