// SPDX-License-Identifier: GPL-2.0-only

#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <errno.h>
#define __iomem
#define BIT(n) (1UL << (n))
#define GENMASK(h,l) (((1UL << ((h)+1))-1) & ~((1UL << (l))-1))
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define clamp(v,lo,hi) ((v)<(lo)?(lo):((v)>(hi)?(hi):(v)))
#define GFP_KERNEL 0
#define CLK_DIVIDER_ONE_BASED 1
#define CLK_IGNORE_UNUSED 8
#define CLK_SET_RATE_PARENT 4
#define CLK_SET_RATE_GATE 1
#define CLK_SET_PARENT_GATE 2
#define DSI_BYTE_PLL_CLK 0
#define DSI_PIXEL_PLL_CLK 1
#define REG_DSI_20nm_PHY_CTRL_0 0x170
#define REG_DSI_20nm_PHY_CTRL_1 0x174
#define clk_div_mask(w) ((1u << (w))-1)
#define IS_ERR(p) ((intptr_t)(p)<0 && (intptr_t)(p)>-4096)
#define PTR_ERR(p) ((int)(intptr_t)(p))
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
struct clk_hw; struct clk_rate_request { unsigned long rate; };
struct clk_ops {
 int (*prepare)(struct clk_hw *); void (*unprepare)(struct clk_hw *);
 int (*set_rate)(struct clk_hw *, unsigned long, unsigned long);
 long (*round_rate)(struct clk_hw *, unsigned long, unsigned long *);
 unsigned long (*recalc_rate)(struct clk_hw *, unsigned long);
 int (*determine_rate)(struct clk_hw *, struct clk_rate_request *);
 u8 (*get_parent)(struct clk_hw *); int (*set_parent)(struct clk_hw *,u8);
};
struct clk_parent_data { const char *fw_name; };
struct clk_init_data { const char *name; const struct clk_ops *ops; const struct clk_parent_data *parent_data; const struct clk_hw **parent_hws; unsigned num_parents; unsigned long flags; };
struct clk_hw { const struct clk_init_data *init; };
struct device { int dummy; }; struct platform_device { struct device dev; };
struct msm_dsi_phy_cfg { unsigned long min_pll_rate,max_pll_rate; unsigned num_regulators; };
struct clocks { struct clk_hw *hws[2]; };
struct msm_dsi_phy { struct platform_device *pdev; void *base,*pll_base; const struct msm_dsi_phy_cfg *cfg; void *supplies; bool pll_on; struct clk_hw *vco_hw; struct clocks *provided_clocks; unsigned id; };
static int refs, enable_error, polls, fail_poll, registrations, access_count;
static unsigned elapsed_us, cal_at, ready_at, cal_reads, ready_reads;
static u32 posted, pixel, byte, phsel, iptat;
static void writel(u32 val, void *addr) { assert(refs>0); access_count++; uintptr_t a=(uintptr_t)addr; if(a==0x10000140) posted=val; if(a==0x10000144) byte=val; if(a==0x10000148) pixel=val; if(a==0x10000018) phsel=val; if(a==0x1000001c) iptat=val; }
static int regulator_bulk_enable(unsigned n,void *s) { assert(n==2); if(enable_error) return enable_error; refs++; return 0; }
static int regulator_bulk_disable(unsigned n,void *s) { assert(n==2 && refs>0); refs--; return 0; }
static void udelay(unsigned n) { elapsed_us += n; }
static uint64_t div_u64(uint64_t n,unsigned d) { return n/d; }
static void dev_info(struct device *d,const char *f,...) {}
static void dev_err(struct device *d,const char *f,...) {}
static u32 readl(void *addr) {
 assert(refs>0); access_count++;
 if ((uintptr_t)addr != 0x10000150) return 0;
 polls++;
 if (elapsed_us < cal_at) cal_reads++; else ready_reads++;
 return 0x96 | (elapsed_us >= cal_at ? BIT(5):0) | (elapsed_us >= ready_at ? BIT(6):0);
}
static int dev_err_probe(struct device *dev,int err,const char *fmt,...) { return err; }
static void *devm_kzalloc(struct device *d,size_t n,int g) { return calloc(1,n); }
static void *devm_platform_ioremap_resource_byname(struct platform_device *p,const char *s) { return (void *)0x20000000; }
static unsigned long divider_recalc_rate(struct clk_hw *h,unsigned long p,unsigned v,void *table,unsigned flags,unsigned width) { unsigned div=flags & CLK_DIVIDER_ONE_BASED ? v:v+1; assert(div>0); return (p+div-1)/div; }
static int divider_get_val(unsigned long rate,unsigned long p,void *t,u8 w,unsigned flags) { unsigned div=(p+rate-1)/rate; if(!div && (flags&CLK_DIVIDER_ONE_BASED)) return -EINVAL; unsigned val=flags&CLK_DIVIDER_ONE_BASED ? div:div-1; return val>clk_div_mask(w) ? clk_div_mask(w):val; }
static int divider_determine_rate(struct clk_hw *h,struct clk_rate_request *r,void *t,u8 w,unsigned flags) { return 0; }
static int clk_mux_determine_rate_flags(struct clk_hw *h,struct clk_rate_request *r,unsigned flags) { return 0; }
static int devm_clk_hw_register(struct device *d,struct clk_hw *hw) { registrations++; if(hw->init->ops->recalc_rate) assert(hw->init->ops->recalc_rate(hw,0)==0); if(hw->init->ops->get_parent) assert(hw->init->ops->get_parent(hw)<=1); return 0; }
static struct clk_hw *devm_clk_hw_register_fixed_factor_parent_hw(struct device *d,const char *n,struct clk_hw *p,unsigned long f,unsigned m,unsigned div) { registrations++; return calloc(1,sizeof(struct clk_hw)); }
