# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import subprocess
R=Path(__file__).resolve().parents[4]
s=(R/'linux/drivers/gpu/drm/msm/dsi/phy/dsi_phy_20nm.c').read_text();a=s.index('#define PLL_SYS_CLK_CTRL');b=s.index('static void dsi_20nm_dphy_set_timing(');body=s[a:b];code=(Path(__file__).parent/'pll-model-prefix.inc').read_text()+body+'\n'+(Path(__file__).parent/'pll-model-main.inc').read_text()
code=code.replace(', fail_poll,', ',')
code=code.replace('static u32 posted, pixel, byte, phsel, iptat;',r'''static u32 posted, pixel, byte, phsel, iptat;
static u32 tune_input=0x29,kvco_input=0x12;static unsigned nwrites;
static struct {uintptr_t addr;u32 value;} writes[4096];
#define dev_dbg dev_info
#define dev_info_once dev_info
static u32 last_write(uintptr_t addr,unsigned start){for(unsigned i=nwrites;i>start;i--)if(writes[i-1].addr==addr)return writes[i-1].value;return UINT32_MAX;}
''')
code=code.replace('assert(refs>0); access_count++; uintptr_t a=(uintptr_t)addr;', 'assert(refs>0);assert(nwrites<4096);writes[nwrites].addr=(uintptr_t)addr;writes[nwrites++].value=val;access_count++; uintptr_t a=(uintptr_t)addr;')
code=code.replace('if ((uintptr_t)addr != 0x10000150) return 0;', 'if((uintptr_t)addr==0x10000160)return tune_input;\n if((uintptr_t)addr==0x10000168)return kvco_input;\n if ((uintptr_t)addr != 0x10000150) return 0;')
code=code.replace('assert(pll_20nm_set_rate(&pll->hw,1687680000,19200000)==0);','assert(pll_20nm_prepare(&pll->hw)==-EINVAL && refs==0 && !access_count);\n assert(pll_20nm_set_rate(&pll->hw,1687680000,19200000)==0);',1)
needle='assert(posted==pll->post_div && pixel==pll->pixel_div && byte==3 && phsel==8 && iptat==14);';code=code.replace(needle,needle+r'''
 assert(pll->trims_valid&&pll->locking_rate==pll->rate&&pll->vco_tune==0x29&&pll->kvco_code==0x12);
 assert(last_write(0x10000074,0)==0&&last_write(0x100000a8,0)==0&&last_write(0x1000004c,0)==0x24);
''')
needle='assert(pll_20nm_prepare(&pll->hw)==0 && posted==preserved && pixel==5);';code=code.replace(needle,r'''
 unsigned warm_start=nwrites;tune_input=0x27;kvco_input=0x13;
 '''+needle+r'''
 assert(pll->vco_tune==0x29&&pll->kvco_code==0x12&&pll->locking_rate==pll->rate);
 assert(last_write(0x10000074,warm_start)==0x32&&last_write(0x100000a8,warm_start)==0xa9);
 assert(last_write(0x1000004c,warm_start)==0xac&&last_write(0x1000002c,warm_start)==0x28);
 assert(last_write(0x10000050,warm_start)==UINT32_MAX);
 puts("PASS same-rate relock uses own cached trims, override masks and bypass sequence; no recalibration/re-read");
''')
code=code.replace('assert(polls==(stage==1 ? 15:16));','assert(polls==(stage==1 ? 15:16));assert(!pll->trims_valid&&pll->locking_rate==0);')
needle=' return 0;\n}\n';assert code.endswith(needle)
code=code[:-len(needle)]+r'''
 unsigned changed_start=nwrites;tune_input=0x129;kvco_input=0x52;
 assert(!pll_20nm_set_rate(&pll->hw,1536000000,19200000));assert(!pll_20nm_prepare(&pll->hw));
 assert(pll->locking_rate==1536000000&&pll->vco_tune==0x129&&pll->kvco_code==0x52);
 assert(last_write(0x10000074,changed_start)==0&&last_write(0x100000a8,changed_start)==0&&last_write(0x1000004c,changed_start)==0x24);
 pll_20nm_unprepare(&pll->hw);unsigned cached_start=nwrites;assert(!pll_20nm_prepare(&pll->hw));
 assert(last_write(0x10000074,cached_start)==0x32&&last_write(0x100000a8,cached_start)==0xa9);
 puts("PASS changed VCO rate recalibrates and updates cache; cached overrides mask only vendor-defined fields");
 pll_20nm_unprepare(&pll->hw);
 return 0;
}
'''
p=R/'build/validation/oem-pll-tests.c';p.parent.mkdir(parents=True, exist_ok=True);p.write_text(code);subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-unused-function',str(p),'-o',str(p.with_suffix(''))],check=True);subprocess.run([str(p.with_suffix(''))],check=True)
# Match the constants against the primary OEM implementation.
v=(R/'kernel_xiaomi_msm8992/drivers/clk/qcom/mdss/mdss-dsi-20nm-pll-util.c').read_text()
for value in ('(dsi_pll_res->cache_pll_trim_codes[0] & 0x3f) | BIT(5)','(dsi_pll_res->cache_pll_trim_codes[1] & 0x7f) | BIT(7)','MMSS_DSI_PHY_PLL_RESETSM_CNTRL, 0xac','MMSS_DSI_PHY_PLL_PLL_BKG_KVCO_CAL_EN, 0x28'):
 assert value in v,value
assert 'pll_20nm_cache_trim_codes(dsi_pll_res);' in v
assert 'Always calibrate on a cold start' not in s
print('PASS trim masks/bypass values and initial-vs-same-rate policy match OEM source')
