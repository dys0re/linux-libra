/* SPDX-License-Identifier: GPL-2.0-only */
/* PMI8994 formats from Xiaomi's qpnp-fg.c and qpnp-smbcharger.c. */
#ifndef QCOM_PMI8994_BATTERY_H
#define QCOM_PMI8994_BATTERY_H

static int pmi8994_capacity(unsigned int raw)
{
	if (!raw)
		return 0;
	if (raw == 255)
		return 100;
	return DIV_ROUND_CLOSEST((raw - 1) * 98, 253) + 1;
}

static int pmi8994_voltage(unsigned int raw)
{
	return (u64)raw * 152587 / 1000;
}

static int pmi8994_current(unsigned int raw)
{
	/* OEM FG is positive on discharge; power_supply is positive on charge. */
	return -div_s64((s64)(s16)raw * 152587, 1000);
}

static int pmi8994_temperature(unsigned int raw)
{
	return (s16)raw * 625 / 1000 - 2730;
}

static const int pmi8994_current_ma[] = {
	300, 400, 450, 475, 500, 550, 600, 650,
	700, 900, 950, 1000, 1100, 1200, 1400, 1450,
	1500, 1600, 1800, 1850, 1880, 1910, 1930, 1950,
	1970, 2000, 2050, 2100, 2300, 2400, 2500, 3000,
};

static int pmi8994_current_code(int ua)
{
	int i;

	for (i = ARRAY_SIZE(pmi8994_current_ma) - 1; i >= 0; i--)
		if (ua >= pmi8994_current_ma[i] * 1000)
			return i;
	return -EINVAL;
}

static int pmi8994_float_voltage(unsigned int code)
{
	if (code < 5 || code > 0x33)
		return -ENODATA;
	if (code <= 0x2a)
		return (3600 + (code - 5) * 20) * 1000;
	if (code <= 0x2c)
		return (4340 + (code - 0x2a) * 10) * 1000;
	return (4360 + (code - 0x2c) * 20) * 1000;
}

static int pmi8994_status(bool online, unsigned int rt, unsigned int sts)
{
	if (!online)
		return POWER_SUPPLY_STATUS_DISCHARGING;
	if (rt & (BIT(7) | BIT(1)))
		return POWER_SUPPLY_STATUS_FULL;
	if (sts & BIT(3))
		return POWER_SUPPLY_STATUS_NOT_CHARGING;
	return sts & GENMASK(2, 1) ? POWER_SUPPLY_STATUS_CHARGING :
		POWER_SUPPLY_STATUS_DISCHARGING;
}

static int pmi8994_health(unsigned int rt)
{
	if (rt & BIT(0))
		return POWER_SUPPLY_HEALTH_OVERHEAT;
	if (rt & BIT(2))
		return POWER_SUPPLY_HEALTH_COLD;
	if (rt & BIT(1))
		return POWER_SUPPLY_HEALTH_WARM;
	if (rt & BIT(3))
		return POWER_SUPPLY_HEALTH_COOL;
	return POWER_SUPPLY_HEALTH_GOOD;
}

#endif
