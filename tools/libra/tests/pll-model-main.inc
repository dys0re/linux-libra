// SPDX-License-Identifier: GPL-2.0-only
int main(void) {
 struct platform_device dev={0}; struct clocks clocks={0};
 struct msm_dsi_phy_cfg cfg={1000000000,2000000000,2};
 struct msm_dsi_phy phy={.pdev=&dev,.cfg=&cfg,.base=(void *)0x30000000,.pll_base=(void *)0x10000000,.provided_clocks=&clocks};
 assert(dsi_pll_20nm_8992_init(&phy)==0);
 struct dsi_pll_20nm *pll=to_pll_20nm(phy.vco_hw);
 assert(registrations==7 && access_count==0 && refs==0);
 puts("PASS registration and initial CCF queries perform zero MMIO");
 assert(pll_20nm_set_rate(&pll->hw,1687680000,19200000)==0);
 assert(pll_20nm_set_rate(&pll->hw,999999999,19200000)==-EINVAL);
 assert(pll_20nm_set_rate(&pll->hw,2000000001,19200000)==-EINVAL);
 assert(pll_20nm_set_rate(&pll->hw,1687680000,24000000)==-EINVAL);
 assert(dsi_20nm_mux_set_parent(&pll->byte_mux.hw,1)==0);
 assert(dsi_20nm_div_set_rate(&pll->ndiv.hw,843840000,1687680000)==0);
 assert(dsi_20nm_div_set_rate(&pll->pixel.hw,281280000,1687680000)==0);
 assert(dsi_20nm_div_recalc_rate(&pll->ndiv.hw,1687680000)==843840000);
 assert(dsi_20nm_div_recalc_rate(&pll->pixel.hw,1687680000)==281280000);
 assert(pll->post_div==0xa2 && pll->pixel_div==5);
 assert(dsi_20nm_mux_get_parent(&pll->byte_mux.hw)==1);
 u32 preserved=pll->post_div;
 assert(dsi_20nm_mux_set_parent(&pll->byte_mux.hw,2)==-EINVAL && pll->post_div==preserved);
 assert(dsi_20nm_div_set_rate(&pll->ndiv.hw,0,1687680000)==-EINVAL && pll->post_div==preserved);
 assert(access_count==0);
 puts("PASS powered-off rate/mux changes preserve shared fields and avoid MMIO");
 enable_error=-EIO;
 assert(pll_20nm_prepare(&pll->hw)==-EIO && refs==0 && access_count==0);
 enable_error=0;
 /* Cold calibration at 12 ms used to fail under the 1 ms window. */
 elapsed_us=0; polls=0; cal_at=12000; ready_at=24000;
 assert(pll_20nm_prepare(&pll->hw)==0 && phy.pll_on && refs==1);
 assert(posted==pll->post_div && pixel==pll->pixel_div && byte==3 && phsel==8 && iptat==14);
 int before=access_count;
 assert(pll_20nm_prepare(&pll->hw)==0 && refs==1 && access_count==before);
 pll_20nm_unprepare(&pll->hw);
 assert(!phy.pll_on && refs==0);
 before=access_count; pll_20nm_unprepare(&pll->hw); assert(access_count==before && refs==0);
 puts("PASS prepare applies cached dividers with supplies on; unprepare balances them");
 assert(pll_20nm_prepare(&pll->hw)==0 && posted==preserved && pixel==5);
 pll_20nm_unprepare(&pll->hw);
 puts("PASS delayed calibration and ready each succeed within independent vendor windows");
 for (int stage=1; stage<=2; stage++) {
   elapsed_us=0; polls=0; cal_reads=ready_reads=0;
   cal_at=stage==1 ? 16000:0; ready_at=32000;
   assert(pll_20nm_prepare(&pll->hw)==-ETIMEDOUT && refs==0 && !phy.pll_on);
   assert(polls==(stage==1 ? 15:16));
   assert(elapsed_us==15010);
 }
 puts("PASS calibration/ready timeouts preserve 15 reads, 1 ms delay, errors and supply cleanup");
 elapsed_us=0; polls=0; cal_at=0; ready_at=0;
 assert(pll_20nm_prepare(&pll->hw)==0 && polls==2 && refs==1);
 pll_20nm_unprepare(&pll->hw);
 puts("PASS immediately locked hardware has no polling delay and balanced cleanup");
 return 0;
}
