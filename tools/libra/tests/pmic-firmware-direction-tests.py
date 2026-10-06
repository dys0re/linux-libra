# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import subprocess,re
R=Path(__file__).resolve().parents[4];pmic=(R/'linux/drivers/pinctrl/qcom/pinctrl-spmi-gpio.c').read_text();gpio=(R/'linux/drivers/gpio/gpiolib.c').read_text()
def fn(s,n):
 a=re.search(r'(?:static )?int '+n+r'\(',s).start();b=s.index('{',a);i=b+1;d=1
 while d:d+=(s[i]=='{')-(s[i]=='}');i+=1
 return s[a:i]
prefix=r'''
#include <stdbool.h>
#include <stdio.h>
#include <assert.h>
#include <errno.h>
#define ENOTSUPP 524
#define GPIO_LINE_DIRECTION_OUT 0
#define GPIO_LINE_DIRECTION_IN 1
#define FLAG_OPEN_DRAIN 0
#define FLAG_IS_OUT 1
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define IS_ERR_OR_NULL(p) (!(p))
static bool test_bit(unsigned n,const unsigned long*p){return !!(*p&(1ul<<n));}
static void assign_bit(unsigned n,unsigned long*p,bool v){if(v)*p|=1ul<<n;else *p&=~(1ul<<n);}
struct pmic_gpio_pad {bool output_enabled,input_enabled;int out_value;};
struct pin {void *drv_data;};struct pinctrl_desc {struct pin *pins;};struct pinctrl_dev {struct pinctrl_desc *desc;};struct pmic_gpio_state {struct pinctrl_dev *ctrl;};
struct gpio_chip {void *data;int(*get_direction)(struct gpio_chip*,unsigned);};
static void *gpiochip_get_data(struct gpio_chip *c){return c->data;}
struct gpio_desc {struct gpio_chip *chip;unsigned int offset;unsigned long flags;};
struct gpio_chip_guard {struct gpio_chip *gc;};
static struct gpio_chip_guard new_guard(struct gpio_desc*d){return (struct gpio_chip_guard){d->chip};}
#define CLASS(t,n) struct t n = new_guard
static unsigned int gpio_chip_hwgpio(struct gpio_desc*d){return d->offset;}
'''
body=fn(pmic,'pmic_gpio_get_direction')+'\n'+fn(gpio,'gpiod_get_direction')
main=r'''
int main(void){
 struct pmic_gpio_pad pad={.output_enabled=true,.input_enabled=false,.out_value=1};struct pin pins[]={{&pad}};struct pinctrl_desc pdesc={pins};struct pinctrl_dev pdev={&pdesc};struct pmic_gpio_state state={&pdev};struct gpio_chip chip={.data=&state};struct gpio_desc desc={.chip=&chip};
 // Actual gpiolib used by v48: output direction unavailable without provider callback.
 assert(gpiod_get_direction(&desc)==-ENOTSUPP);assert(!desc.flags&&pad.output_enabled&&pad.out_value==1);
 chip.get_direction=pmic_gpio_get_direction;assert(!gpiod_get_direction(&desc));assert(test_bit(FLAG_IS_OUT,&desc.flags));assert(pad.output_enabled&&pad.out_value==1);
 pad.output_enabled=false;pad.input_enabled=true;assert(gpiod_get_direction(&desc)==GPIO_LINE_DIRECTION_IN);assert(!test_bit(FLAG_IS_OUT,&desc.flags));assert(pad.input_enabled&&pad.out_value==1);
 pad.output_enabled=true;pad.input_enabled=true;assert(gpiod_get_direction(&desc)==GPIO_LINE_DIRECTION_OUT);assert(test_bit(FLAG_IS_OUT,&desc.flags));assert(pad.output_enabled&&pad.input_enabled&&pad.out_value==1);
 pad.output_enabled=false;assert(gpiod_get_direction(&desc)==GPIO_LINE_DIRECTION_IN);assert(!test_bit(FLAG_IS_OUT,&desc.flags));
 desc.chip=NULL;assert(gpiod_get_direction(&desc)==-ENODEV);assert(gpiod_get_direction(NULL)==-EINVAL);
 puts("PASS actual gpiolib + PMIC callback: reproduced v48 ENOTSUPP rejection, firmware output/input/in-out direction visible, descriptor flags updated, pad direction/value unchanged, detached/invalid descriptors rejected.");
}
'''
p=R/'build/validation/pmic-firmware-direction-tests.c';p.parent.mkdir(parents=True, exist_ok=True);p.write_text(prefix+body+main);subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',str(p),'-o',str(p.with_suffix(''))],check=True);subprocess.run([str(p.with_suffix(''))],check=True)
assert '.get_direction\t\t= pmic_gpio_get_direction' in pmic
assert 'pad->output_enabled = true;' in pmic[pmic.index('static int pmic_gpio_populate('):]
assert 'pad->output_enabled = arg ? true : false;' in pmic
print('PASS callback wired to gpio_chip; firmware population and configuration supply cached direction')
