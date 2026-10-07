// SPDX-License-Identifier: GPL-2.0-only
/*
 * PMI8994 fuel gauge and charger telemetry for Xiaomi Libra.
 * Register formats and conversions follow the OEM qpnp-fg / smbcharger.
 * Keep the running gauge profile, learned data, thermistor configuration,
 * charger detection, float voltage and hardware JEITA protection intact.
 */
#include <linux/delay.h>
#include <linux/interrupt.h>
#include <linux/iopoll.h>
#include <linux/math64.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/power_supply.h>
#include <linux/property.h>
#include <linux/regmap.h>
#include <linux/unaligned.h>
#include <linux/workqueue.h>
#include "qcom_pmi8994_battery.h"

#define MEM_CFG		0x4440
#define MEM_CTL		0x4441
#define MEM_ADDR		0x4442
#define MEM_DATA		0x444c
#define MEM_RT		0x4410
#define MEM_REQUEST	BIT(7)
#define MEM_AVAILABLE	BIT(0)
#define CHGR_FCC		0x10f2
#define BAT_CMD		0x1242
#define BAT_DISABLE	BIT(1)

struct pmi8994_snapshot {
	int capacity, voltage, current_ua, temp, full_design;
	int present, online, status, health, usb_type;
	bool valid;
};

struct pmi8994_battery {
	struct device *dev;
	struct regmap *map;
	struct mutex lock;
	struct delayed_work update;
	struct power_supply *battery, *usb;
	struct pmi8994_snapshot data;
	unsigned int fcc_ceiling, automatic_cmd;
	unsigned int voltage_max;
	bool stopping;
};

/* Caller owns MEM_REQUEST and lock. Never select SRAM write mode. */
static int pmi8994_sram_read(struct pmi8994_battery *b, unsigned int addr,
			     u8 *data, size_t len)
{
	u8 address[2];
	unsigned int chunk;
	int ret;

	while (len) {
		chunk = min_t(size_t, len, 4 - (addr & 3));
		put_unaligned_le16(addr & ~3, address);
		ret = regmap_bulk_write(b->map, MEM_ADDR, address, 2);
		if (ret)
			return ret;
		ret = regmap_bulk_read(b->map, MEM_DATA + (addr & 3), data, chunk);
		if (ret)
			return ret;
		addr += chunk;
		data += chunk;
		len -= chunk;
	}
	return 0;
}

/* Keep a single grant for the entire sample and release it on every error. */
static int pmi8994_gauge_read(struct pmi8994_battery *b,
			      struct pmi8994_snapshot *s)
{
	unsigned int cfg, ctl, rt;
	u8 raw[4], temp[2], nominal[2], integrity;
	int ret, cleanup;

	ret = regmap_read(b->map, MEM_CFG, &cfg);
	if (ret)
		return ret;
	if (cfg & MEM_REQUEST)
		return -EBUSY;
	ret = regmap_read(b->map, MEM_CTL, &ctl);
	if (ret)
		return ret;
	ret = regmap_update_bits(b->map, MEM_CFG, MEM_REQUEST, MEM_REQUEST);
	if (ret)
		return ret;
	ret = regmap_read_poll_timeout(b->map, MEM_RT, rt,
				      rt & MEM_AVAILABLE, 5000, 5000000);
	if (ret)
		goto release;
	ret = regmap_write(b->map, MEM_CTL, 0);
	if (ret)
		goto release;
	ret = pmi8994_sram_read(b, 0x53c, &integrity, 1);
	if (ret)
		goto release;
	if (!(integrity & BIT(0))) {
		ret = -ENODATA;
		goto release;
	}
	ret = pmi8994_sram_read(b, 0x5cd, raw, 4);
	if (ret)
		goto release;
	ret = pmi8994_sram_read(b, 0x552, temp, 2);
	if (ret)
		goto release;
	ret = pmi8994_sram_read(b, 0x4f4, nominal, 2);
	if (ret)
		goto release;
	s->voltage = pmi8994_voltage(get_unaligned_le16(raw));
	s->current_ua = pmi8994_current(get_unaligned_le16(raw + 2));
	s->temp = pmi8994_temperature(get_unaligned_le16(temp));
	s->full_design = get_unaligned_le16(nominal) * 1000;
release:
	cleanup = regmap_write(b->map, MEM_CTL, ctl);
	if (!ret)
		ret = cleanup;
	cleanup = regmap_update_bits(b->map, MEM_CFG, MEM_REQUEST, 0);
	return ret ?: cleanup;
}

static int pmi8994_read_sample(struct pmi8994_battery *b,
			       struct pmi8994_snapshot *s)
{
	unsigned int usb_rt, input, bat_rt, present, chg_rt, chg_sts, type;
	u8 soc[2];
	int ret, tries;

	ret = regmap_read(b->map, 0x1310, &usb_rt);
	if (ret)
		return ret;
	ret = regmap_read(b->map, 0x130d, &input);
	if (ret)
		return ret;
	ret = regmap_read(b->map, 0x1210, &bat_rt);
	if (ret)
		return ret;
	ret = regmap_read(b->map, 0x1208, &present);
	if (ret)
		return ret;
	ret = regmap_read(b->map, 0x1010, &chg_rt);
	if (ret)
		return ret;
	ret = regmap_read(b->map, 0x100e, &chg_sts);
	if (ret)
		return ret;
	ret = regmap_read(b->map, 0x1608, &type);
	if (ret)
		return ret;
	s->online = (usb_rt & BIT(2)) && !(usb_rt & BIT(1)) &&
		    (input & GENMASK(5, 3));
	s->present = !!(present & BIT(7));
	s->health = pmi8994_health(bat_rt);
	s->status = pmi8994_status(s->online, chg_rt, chg_sts);
	s->usb_type = type & BIT(4) ? POWER_SUPPLY_USB_TYPE_SDP :
		type & BIT(7) ? POWER_SUPPLY_USB_TYPE_CDP :
		type & (BIT(5) | BIT(6)) ? POWER_SUPPLY_USB_TYPE_DCP :
		POWER_SUPPLY_USB_TYPE_UNKNOWN;
	if (!s->present)
		return 0;
	for (tries = 0; tries < 5; tries++) {
		ret = regmap_bulk_read(b->map, 0x4009, soc, 2);
		if (ret)
			return ret;
		if (soc[0] == soc[1])
			break;
	}
	if (tries == 5)
		return -EAGAIN;
	s->capacity = pmi8994_capacity(soc[0]);
	ret = regmap_read(b->map, 0x4010, &type);
	if (ret)
		return ret;
	if (type & BIT(3))
		s->capacity = 0;
	ret = pmi8994_gauge_read(b, s);
	if (!ret)
		s->valid = true;
	return ret;
}

static void pmi8994_update(struct work_struct *work)
{
	struct pmi8994_battery *b = container_of(work, struct pmi8994_battery,
					       update.work);
	struct pmi8994_snapshot s = {};
	int ret;

	mutex_lock(&b->lock);
	ret = pmi8994_read_sample(b, &s);
	/* Never expose a previous sample as a current measurement after a failure. */
	if (ret)
		s.valid = false;
	b->data = s;
	mutex_unlock(&b->lock);
	if (ret)
		dev_warn_ratelimited(b->dev, "battery sample unavailable: %d\n", ret);
	power_supply_changed(b->battery);
	power_supply_changed(b->usb);
	if (!READ_ONCE(b->stopping))
		schedule_delayed_work(&b->update, msecs_to_jiffies(ret ? 5000 : 10000));
}

static irqreturn_t pmi8994_changed(int irq, void *data)
{
	struct pmi8994_battery *b = data;

	if (!READ_ONCE(b->stopping))
		mod_delayed_work(system_wq, &b->update, 0);
	return IRQ_HANDLED;
}

static enum power_supply_property pmi8994_battery_props[] = {
	POWER_SUPPLY_PROP_STATUS, POWER_SUPPLY_PROP_PRESENT,
	POWER_SUPPLY_PROP_HEALTH, POWER_SUPPLY_PROP_TECHNOLOGY,
	POWER_SUPPLY_PROP_CAPACITY, POWER_SUPPLY_PROP_VOLTAGE_NOW,
	POWER_SUPPLY_PROP_CURRENT_NOW, POWER_SUPPLY_PROP_TEMP,
	POWER_SUPPLY_PROP_POWER_NOW,
	POWER_SUPPLY_PROP_CHARGE_FULL_DESIGN, POWER_SUPPLY_PROP_VOLTAGE_MAX_DESIGN,
	POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT,
	POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT_MAX,
	POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE,
	POWER_SUPPLY_PROP_CHARGE_BEHAVIOUR,
};

static int pmi8994_battery_get(struct power_supply *psy,
			     enum power_supply_property prop,
			     union power_supply_propval *val)
{
	struct pmi8994_battery *b = power_supply_get_drvdata(psy);
	struct pmi8994_snapshot s;
	unsigned int reg;
	int ret = 0;

	mutex_lock(&b->lock);
	s = b->data;
	switch (prop) {
	case POWER_SUPPLY_PROP_PRESENT: val->intval = s.present; break;
	case POWER_SUPPLY_PROP_TECHNOLOGY: val->intval = POWER_SUPPLY_TECHNOLOGY_LION; break;
	case POWER_SUPPLY_PROP_STATUS: val->intval = s.status; break;
	case POWER_SUPPLY_PROP_HEALTH: val->intval = s.health; break;
	case POWER_SUPPLY_PROP_VOLTAGE_MAX_DESIGN: val->intval = b->voltage_max; break;
	case POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT_MAX: val->intval = b->fcc_ceiling; break;
	case POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT:
		ret = regmap_read(b->map, CHGR_FCC, &reg);
		if (!ret)
			val->intval = pmi8994_current_ma[reg & 31] * 1000;
		break;
	case POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE:
		ret = regmap_read(b->map, 0x10f4, &reg);
		if (!ret) {
			ret = pmi8994_float_voltage(reg & 63);
			if (ret >= 0) { val->intval = ret; ret = 0; }
		}
		break;
	case POWER_SUPPLY_PROP_CHARGE_BEHAVIOUR:
		ret = regmap_read(b->map, BAT_CMD, &reg);
		if (!ret)
			val->intval = reg & BAT_DISABLE ?
				POWER_SUPPLY_CHARGE_BEHAVIOUR_INHIBIT_CHARGE :
				POWER_SUPPLY_CHARGE_BEHAVIOUR_AUTO;
		break;
	default:
		if (!s.valid) { ret = -ENODATA; break; }
		switch (prop) {
		case POWER_SUPPLY_PROP_CAPACITY: val->intval = s.capacity; break;
		case POWER_SUPPLY_PROP_VOLTAGE_NOW: val->intval = s.voltage; break;
		case POWER_SUPPLY_PROP_CURRENT_NOW: val->intval = s.current_ua; break;
		case POWER_SUPPLY_PROP_POWER_NOW:
			val->intval = div_s64((s64)s.voltage * s.current_ua, 1000000);
			break;
		case POWER_SUPPLY_PROP_TEMP: val->intval = s.temp; break;
		case POWER_SUPPLY_PROP_CHARGE_FULL_DESIGN: val->intval = s.full_design; break;
		default: ret = -EINVAL;
		}
	}
	mutex_unlock(&b->lock);
	return ret;
}

static int pmi8994_battery_set(struct power_supply *psy,
			     enum power_supply_property prop,
			     const union power_supply_propval *val)
{
	struct pmi8994_battery *b = power_supply_get_drvdata(psy);
	unsigned long flags;
	int code, ret = -EINVAL;

	mutex_lock(&b->lock);
	if (prop == POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT) {
		if (val->intval > b->fcc_ceiling || val->intval < 300000)
			goto out;
		code = pmi8994_current_code(val->intval);
		/* OEM secure-access sequence must be adjacent, with no other writer. */
		local_irq_save(flags);
		ret = regmap_write(b->map, 0x10d0, 0xa5);
		if (!ret)
			ret = regmap_update_bits(b->map, CHGR_FCC, 31, code);
		local_irq_restore(flags);
	} else if (prop == POWER_SUPPLY_PROP_CHARGE_BEHAVIOUR) {
		if (val->intval == POWER_SUPPLY_CHARGE_BEHAVIOUR_INHIBIT_CHARGE)
			ret = regmap_update_bits(b->map, BAT_CMD, BAT_DISABLE, BAT_DISABLE);
		else if (val->intval == POWER_SUPPLY_CHARGE_BEHAVIOUR_AUTO)
			/* Return to the bootloader's state, never force-enable charging. */
			ret = regmap_update_bits(b->map, BAT_CMD, BAT_DISABLE, b->automatic_cmd);
	}
out:
	mutex_unlock(&b->lock);
	if (!ret)
		mod_delayed_work(system_wq, &b->update, 0);
	return ret;
}

static int pmi8994_battery_writable(struct power_supply *psy,
				 enum power_supply_property prop)
{
	return prop == POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT ||
	       prop == POWER_SUPPLY_PROP_CHARGE_BEHAVIOUR;
}

static const struct power_supply_desc pmi8994_battery_desc = {
	.name = "battery", .type = POWER_SUPPLY_TYPE_BATTERY,
	.properties = pmi8994_battery_props,
	.num_properties = ARRAY_SIZE(pmi8994_battery_props),
	.get_property = pmi8994_battery_get,
	.set_property = pmi8994_battery_set,
	.property_is_writeable = pmi8994_battery_writable,
	.charge_behaviours = BIT(POWER_SUPPLY_CHARGE_BEHAVIOUR_AUTO) |
			     BIT(POWER_SUPPLY_CHARGE_BEHAVIOUR_INHIBIT_CHARGE),
};

static enum power_supply_property pmi8994_usb_props[] = {
	POWER_SUPPLY_PROP_ONLINE, POWER_SUPPLY_PROP_USB_TYPE,
};
static int pmi8994_usb_get(struct power_supply *psy,
			 enum power_supply_property prop,
			 union power_supply_propval *val)
{
	struct pmi8994_battery *b = power_supply_get_drvdata(psy);
	int ret = 0;

	mutex_lock(&b->lock);
	if (prop == POWER_SUPPLY_PROP_ONLINE)
		val->intval = b->data.online;
	else if (prop == POWER_SUPPLY_PROP_USB_TYPE)
		val->intval = b->data.usb_type;
	else
		ret = -EINVAL;
	mutex_unlock(&b->lock);
	return ret;
}
static const struct power_supply_desc pmi8994_usb_desc = {
	.name = "usb", .type = POWER_SUPPLY_TYPE_USB,
	.properties = pmi8994_usb_props,
	.num_properties = ARRAY_SIZE(pmi8994_usb_props),
	.usb_types = BIT(POWER_SUPPLY_USB_TYPE_UNKNOWN) |
		     BIT(POWER_SUPPLY_USB_TYPE_SDP) |
		     BIT(POWER_SUPPLY_USB_TYPE_DCP) |
		     BIT(POWER_SUPPLY_USB_TYPE_CDP),
	.get_property = pmi8994_usb_get,
};

static void pmi8994_stop(void *data)
{
	struct pmi8994_battery *b = data;

	WRITE_ONCE(b->stopping, true);
	cancel_delayed_work_sync(&b->update);
}

static int pmi8994_battery_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct power_supply_config config = {};
	struct pmi8994_battery *b;
	static const unsigned int bases[] = {0x1000, 0x4000, 0x4100, 0x4400};
	static const unsigned int subtypes[] = {1, 9, 10, 12};
	unsigned int reg, ceiling;
	int ret, i, irq, num_irqs;

	b = devm_kzalloc(dev, sizeof(*b), GFP_KERNEL);
	if (!b)
		return -ENOMEM;
	b->dev = dev;
	b->map = dev_get_regmap(dev->parent, NULL);
	if (!b->map)
		return -ENODEV;
	/* This layout is specific to PMI8994, not the later SMB2 PMICs. */
	for (i = 0; i < ARRAY_SIZE(bases); i++) {
		ret = regmap_read(b->map, bases[i] + 5, &reg);
		if (ret)
			return dev_err_probe(dev, ret, "reading peripheral subtype\n");
		if (reg != subtypes[i])
			return -ENODEV;
	}
	ret = device_property_read_u32(dev, "qcom,fast-charge-current-max-microamp", &ceiling);
	if (ret)
		return ret;
	ret = device_property_read_u32(dev, "qcom,battery-voltage-max-microvolt", &b->voltage_max);
	if (ret)
		return ret;
	if (ceiling < 300000 || ceiling > 1800000 || b->voltage_max != 4400000)
		return -EINVAL;
	ret = regmap_read(b->map, CHGR_FCC, &reg);
	if (ret)
		return ret;
	/* User controls can reduce the inherited limit; they cannot raise it. */
	b->fcc_ceiling = min(ceiling, pmi8994_current_ma[reg & 31] * 1000U);
	ret = regmap_read(b->map, BAT_CMD, &reg);
	if (ret)
		return ret;
	b->automatic_cmd = reg & BAT_DISABLE;
	mutex_init(&b->lock);
	INIT_DELAYED_WORK(&b->update, pmi8994_update);
	config.drv_data = b;
	config.of_node = dev->of_node;
	b->battery = devm_power_supply_register(dev, &pmi8994_battery_desc, &config);
	if (IS_ERR(b->battery))
		return PTR_ERR(b->battery);
	b->usb = devm_power_supply_register(dev, &pmi8994_usb_desc, &config);
	if (IS_ERR(b->usb))
		return PTR_ERR(b->usb);
	/* Registered before IRQs so devres frees handlers before cancelling work. */
	ret = devm_add_action_or_reset(dev, pmi8994_stop, b);
	if (ret)
		return ret;
	num_irqs = platform_irq_count(pdev);
	if (num_irqs < 0)
		return dev_err_probe(dev, num_irqs, "looking up battery IRQs\n");
	for (i = 0; i < num_irqs; i++) {
		irq = platform_get_irq(pdev, i);
		if (irq < 0)
			return irq;
		ret = devm_request_threaded_irq(dev, irq, NULL, pmi8994_changed,
					      IRQF_ONESHOT, dev_name(dev), b);
		if (ret)
			return dev_err_probe(dev, ret, "requesting battery IRQ\n");
	}
	schedule_delayed_work(&b->update, 0);
	dev_info(dev, "PMI8994 battery/USB ready; preserving OEM gauge and charger, current ceiling %u uA\n",
		 b->fcc_ceiling);
	return 0;
}

static const struct of_device_id pmi8994_battery_match[] = {
	{ .compatible = "qcom,pmi8994-battery" }, {}
};
MODULE_DEVICE_TABLE(of, pmi8994_battery_match);
static struct platform_driver pmi8994_battery_driver = {
	.probe = pmi8994_battery_probe,
	.driver = { .name = "qcom-pmi8994-battery", .of_match_table = pmi8994_battery_match },
};
module_platform_driver(pmi8994_battery_driver);
MODULE_DESCRIPTION("Qualcomm PMI8994 OEM fuel gauge and charger telemetry");
MODULE_LICENSE("GPL");
