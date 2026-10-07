// SPDX-License-Identifier: GPL-2.0-only
/* QCA6174 board power sequence from Xiaomi Libra's factory CNSS driver. */
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/regulator/consumer.h>
#include <linux/regulator/driver.h>
#include <linux/regulator/of_regulator.h>

struct qca6174_wlan_power {
	struct regulator_bulk_data supplies[3];
	struct gpio_desc *enable;
	struct gpio_descs *bootstrap;
	bool enabled;
};

static int qca6174_wlan_enable(struct regulator_dev *rdev)
{
	struct qca6174_wlan_power *p = rdev_get_drvdata(rdev);
	int ret, i;

	/* CNSS: PA -> IO -> crystal, then straps, then WLAN_EN. */
	for (i = 0; i < ARRAY_SIZE(p->supplies); i++) {
		ret = regulator_enable(p->supplies[i].consumer);
		if (ret)
			goto err_rails;
	}
	for (i = 0; i < p->bootstrap->ndescs; i++) {
		gpiod_set_value_cansleep(p->bootstrap->desc[i], 1);
		msleep(10);
	}
	gpiod_set_value_cansleep(p->enable, 1);
	usleep_range(10000, 11000);
	p->enabled = true;
	return 0;

err_rails:
	while (i--)
		regulator_disable(p->supplies[i].consumer);
	return ret;
}

static int qca6174_wlan_disable(struct regulator_dev *rdev)
{
	struct qca6174_wlan_power *p = rdev_get_drvdata(rdev);
	int ret = 0, err, i;

	gpiod_set_value_cansleep(p->enable, 0);
	usleep_range(10000, 11000);
	/* Avoid driving bootstrap highs into the unpowered IO rail. */
	for (i = 0; i < p->bootstrap->ndescs; i++)
		gpiod_set_value_cansleep(p->bootstrap->desc[i], 0);
	for (i = ARRAY_SIZE(p->supplies) - 1; i >= 0; i--) {
		err = regulator_disable(p->supplies[i].consumer);
		if (err && !ret)
			ret = err;
	}
	p->enabled = false;
	return ret;
}

static int qca6174_wlan_is_enabled(struct regulator_dev *rdev)
{
	struct qca6174_wlan_power *p = rdev_get_drvdata(rdev);

	return p->enabled;
}

static const struct regulator_ops qca6174_wlan_ops = {
	.enable = qca6174_wlan_enable,
	.disable = qca6174_wlan_disable,
	.is_enabled = qca6174_wlan_is_enabled,
};

static const struct regulator_desc qca6174_wlan_desc = {
	.name = "qca6174-wlan",
	.type = REGULATOR_VOLTAGE,
	.owner = THIS_MODULE,
	.ops = &qca6174_wlan_ops,
};

static int qca6174_wlan_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct regulator_config config = {};
	struct qca6174_wlan_power *p;
	struct regulator_dev *rdev;
	int ret;

	p = devm_kzalloc(dev, sizeof(*p), GFP_KERNEL);
	if (!p)
		return -ENOMEM;
	p->supplies[0].supply = "vddpa";
	p->supplies[1].supply = "vddio";
	p->supplies[2].supply = "vddxo";
	ret = devm_regulator_bulk_get(dev, ARRAY_SIZE(p->supplies), p->supplies);
	if (ret)
		return dev_err_probe(dev, ret, "radio supplies unavailable\n");
	p->enable = devm_gpiod_get(dev, "enable", GPIOD_OUT_LOW);
	if (IS_ERR(p->enable))
		return dev_err_probe(dev, PTR_ERR(p->enable), "WLAN_EN unavailable\n");
	p->bootstrap = devm_gpiod_get_array(dev, "bootstrap", GPIOD_OUT_LOW);
	if (IS_ERR(p->bootstrap))
		return dev_err_probe(dev, PTR_ERR(p->bootstrap), "bootstrap unavailable\n");
	config.dev = dev;
	config.of_node = dev->of_node;
	config.init_data = of_get_regulator_init_data(dev, dev->of_node,
						    &qca6174_wlan_desc);
	config.driver_data = p;
	rdev = devm_regulator_register(dev, &qca6174_wlan_desc, &config);
	return PTR_ERR_OR_ZERO(rdev);
}

static const struct of_device_id qca6174_wlan_match[] = {
	{ .compatible = "qcom,qca6174-wlan-power" },
	{}
};
MODULE_DEVICE_TABLE(of, qca6174_wlan_match);

static struct platform_driver qca6174_wlan_driver = {
	.probe = qca6174_wlan_probe,
	.driver = {
		.name = "qca6174-wlan-power",
		.of_match_table = qca6174_wlan_match,
	},
};
module_platform_driver(qca6174_wlan_driver);
MODULE_DESCRIPTION("Qualcomm QCA6174 WLAN board power sequence");
MODULE_LICENSE("GPL");
