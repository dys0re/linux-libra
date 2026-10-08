// SPDX-License-Identifier: GPL-2.0-only
/*
 * IOMMU API for QCOM secure IOMMUs.  Somewhat based on arm-smmu.c
 *
 * Copyright (C) 2013 ARM Limited
 * Copyright (C) 2017 Red Hat
 */

#include <linux/atomic.h>
#include <linux/bitfield.h>
#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/dma-mapping.h>
#include <linux/err.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/io-64-nonatomic-hi-lo.h>
#include <linux/io-pgtable.h>
#include <linux/iommu.h>
#include <linux/iopoll.h>
#include <linux/kconfig.h>
#include <linux/init.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>
#include <linux/pm.h>
#include <linux/pm_runtime.h>
#include <linux/pm_domain.h>
#include <linux/pm_opp.h>
#include <linux/firmware/qcom/qcom_scm.h>
#include <linux/slab.h>
#include <linux/spinlock.h>

#include "arm-smmu.h"

#define SMMU_INTR_SEL_NS     0x2000
#define MSM8992_ACTLR_BPRC (BIT(28) | BIT(29) | BIT(30))

static bool msm8992_probe;
module_param(msm8992_probe, bool, 0600);
MODULE_PARM_DESC(msm8992_probe, "Allow manual MSM8992 GPU IOMMU activation");

enum qcom_iommu_clk {
	CLK_IFACE,
	CLK_BUS,
	CLK_TBU,
	CLK_NUM,
};

struct qcom_iommu_ctx;

struct qcom_iommu_dev {
	/* IOMMU core code handle */
	struct iommu_device	 iommu;
	struct device		*dev;
	struct clk_bulk_data clks[CLK_NUM];
	void __iomem		*local_base;
	u32			 sec_id;
	u8			 max_asid;
	bool			 msm8992;
	struct qcom_iommu_ctx	*ctxs[];   /* indexed by asid */
};

struct qcom_iommu_ctx {
	struct device		*dev;
	void __iomem		*base;
	bool			 secure_init;
	bool			 secured_ctx;
	u8			 asid;      /* asid and ctx bank # are 1:1 */
	struct iommu_domain	*domain;
	/* MSM8992 loses context registers during GX power collapse. */
	u64 ttbr0;
	u32 tcr, tcr2, mair0, mair1, sctlr;
};

static u32 qcom_iommu_msm8992_tcr(const struct io_pgtable_cfg *cfg)
{
	/* QSMMUv1 uses the AArch32 TTBCR layout, without a TCR2 register. */
	return ARM_SMMU_TCR_EAE | BIT(5) /* EPD1 */ |
		FIELD_PREP(GENMASK(2, 0), 32 - cfg->ias) |
		FIELD_PREP(GENMASK(9, 8), cfg->arm_lpae_s1_cfg.tcr.irgn) |
		FIELD_PREP(GENMASK(11, 10), cfg->arm_lpae_s1_cfg.tcr.orgn) |
		FIELD_PREP(GENMASK(13, 12), cfg->arm_lpae_s1_cfg.tcr.sh);
}

static void qcom_iommu_msm8992_bfb(struct qcom_iommu_dev *iommu)
{
	/* msm8992-iommu.dtsi: global routing and micro-TLB settings. */
	static const struct { u16 reg; u32 value; } bfb[] = {
		{ 0x2000, 3 }, { 0x204c, 3 }, { 0x2060, 0x1555 },
		{ 0x2514, 0 }, { 0x2540, 0 }, { 0x256c, 0x10 },
		{ 0x20ac, 0 }, { 0x215c, 0x120 }, { 0x220c, 0x120 },
		{ 0x22bc, 0x10 }, { 0x2314, 0 }, { 0x2394, 0 },
		{ 0x2414, 0 }, { 0x2494, 1 }, { 0x2008, 0 },
		{ 0x2600, 7 }, { 0x2604, 0 }, { 0x2608, 0x20 },
		{ 0x260c, 0x20 }, { 0x2610, 0xc }, { 0x2614, 0 },
		{ 0x2618, 0 }, { 0x261c, 0 }, { 0x2620, 0x10 },
		{ 0x2624, 0 }, { 0x2628, 0 }, { 0x262c, 0x10 },
	};
	unsigned int i;

	for (i = 0; i < ARRAY_SIZE(bfb); i++)
		writel_relaxed(bfb[i].value, iommu->local_base + bfb[i].reg);
	wmb();
}

struct qcom_iommu_domain {
	struct io_pgtable_ops	*pgtbl_ops;
	spinlock_t		 pgtbl_lock;
	struct mutex		 init_mutex; /* Protects iommu pointer */
	struct iommu_domain	 domain;
	struct qcom_iommu_dev	*iommu;
	struct iommu_fwspec	*fwspec;
};

static struct qcom_iommu_domain *to_qcom_iommu_domain(struct iommu_domain *dom)
{
	return container_of(dom, struct qcom_iommu_domain, domain);
}

static const struct iommu_ops qcom_iommu_ops;

static struct qcom_iommu_ctx * to_ctx(struct qcom_iommu_domain *d, unsigned asid)
{
	struct qcom_iommu_dev *qcom_iommu = d->iommu;
	if (!qcom_iommu)
		return NULL;
	return qcom_iommu->ctxs[asid];
}

static inline void
iommu_writel(struct qcom_iommu_ctx *ctx, unsigned reg, u32 val)
{
	writel_relaxed(val, ctx->base + reg);
}

static inline void
iommu_writeq(struct qcom_iommu_ctx *ctx, unsigned reg, u64 val)
{
	writeq_relaxed(val, ctx->base + reg);
}

static inline u32
iommu_readl(struct qcom_iommu_ctx *ctx, unsigned reg)
{
	return readl_relaxed(ctx->base + reg);
}

static inline u64
iommu_readq(struct qcom_iommu_ctx *ctx, unsigned reg)
{
	return readq_relaxed(ctx->base + reg);
}

static void qcom_iommu_program_context(struct qcom_iommu_ctx *ctx, bool msm8992)
{
	iommu_writel(ctx, ARM_SMMU_CB_SCTLR, 0);
	if (msm8992)
		iommu_writel(ctx, ARM_SMMU_CB_ACTLR, MSM8992_ACTLR_BPRC);
	iommu_writel(ctx, ARM_SMMU_CB_FAR, 0);
	iommu_writel(ctx, ARM_SMMU_CB_FSR, ARM_SMMU_CB_FSR_FAULT);

	/* TCR selects the TTBR format. QSMMUv1 has no register at +0x10. */
	if (!msm8992)
		iommu_writel(ctx, ARM_SMMU_CB_TCR2, ctx->tcr2);
	iommu_writel(ctx, ARM_SMMU_CB_TCR, ctx->tcr);
	iommu_writeq(ctx, ARM_SMMU_CB_TTBR0, ctx->ttbr0);
	iommu_writeq(ctx, ARM_SMMU_CB_TTBR1, 0);
	iommu_writel(ctx, ARM_SMMU_CB_S1_MAIR0, ctx->mair0);
	iommu_writel(ctx, ARM_SMMU_CB_S1_MAIR1, ctx->mair1);
	wmb();
	iommu_writel(ctx, ARM_SMMU_CB_SCTLR, ctx->sctlr);
	wmb();
}

static void qcom_iommu_tlb_sync(void *cookie)
{
	struct qcom_iommu_domain *qcom_domain = cookie;
	struct iommu_fwspec *fwspec = qcom_domain->fwspec;
	unsigned i;

	for (i = 0; i < fwspec->num_ids; i++) {
		struct qcom_iommu_ctx *ctx = to_ctx(qcom_domain, fwspec->ids[i]);
		unsigned int val, ret;

		iommu_writel(ctx, ARM_SMMU_CB_TLBSYNC, 0);

		ret = readl_poll_timeout(ctx->base + ARM_SMMU_CB_TLBSTATUS, val,
					 (val & 0x1) == 0, 0, 5000000);
		if (ret)
			dev_err(ctx->dev, "timeout waiting for TLB SYNC\n");
	}
}

static void qcom_iommu_tlb_inv_context(void *cookie)
{
	struct qcom_iommu_domain *qcom_domain = cookie;
	struct iommu_fwspec *fwspec = qcom_domain->fwspec;
	unsigned i;

	for (i = 0; i < fwspec->num_ids; i++) {
		struct qcom_iommu_ctx *ctx = to_ctx(qcom_domain, fwspec->ids[i]);
		iommu_writel(ctx, ARM_SMMU_CB_S1_TLBIASID, ctx->asid);
	}

	qcom_iommu_tlb_sync(cookie);
}

static void qcom_iommu_tlb_inv_range_nosync(unsigned long iova, size_t size,
					    size_t granule, bool leaf, void *cookie)
{
	struct qcom_iommu_domain *qcom_domain = cookie;
	struct iommu_fwspec *fwspec = qcom_domain->fwspec;
	unsigned i, reg;

	reg = leaf ? ARM_SMMU_CB_S1_TLBIVAL : ARM_SMMU_CB_S1_TLBIVA;

	for (i = 0; i < fwspec->num_ids; i++) {
		struct qcom_iommu_ctx *ctx = to_ctx(qcom_domain, fwspec->ids[i]);
		size_t s = size;

		iova = (iova >> 12) << 12;
		iova |= ctx->asid;
		do {
			iommu_writel(ctx, reg, iova);
			iova += granule;
		} while (s -= granule);
	}
}

static void qcom_iommu_tlb_flush_walk(unsigned long iova, size_t size,
				      size_t granule, void *cookie)
{
	qcom_iommu_tlb_inv_range_nosync(iova, size, granule, false, cookie);
	qcom_iommu_tlb_sync(cookie);
}

static void qcom_iommu_tlb_add_page(struct iommu_iotlb_gather *gather,
				    unsigned long iova, size_t granule,
				    void *cookie)
{
	qcom_iommu_tlb_inv_range_nosync(iova, granule, granule, true, cookie);
}

static const struct iommu_flush_ops qcom_flush_ops = {
	.tlb_flush_all	= qcom_iommu_tlb_inv_context,
	.tlb_flush_walk = qcom_iommu_tlb_flush_walk,
	.tlb_add_page	= qcom_iommu_tlb_add_page,
};

static irqreturn_t qcom_iommu_fault(int irq, void *dev)
{
	struct qcom_iommu_ctx *ctx = dev;
	u32 fsr, fsynr;
	u64 iova;

	fsr = iommu_readl(ctx, ARM_SMMU_CB_FSR);

	if (!(fsr & ARM_SMMU_CB_FSR_FAULT))
		return IRQ_NONE;

	fsynr = iommu_readl(ctx, ARM_SMMU_CB_FSYNR0);
	iova = iommu_readq(ctx, ARM_SMMU_CB_FAR);

	if (!ctx->domain || report_iommu_fault(ctx->domain, ctx->dev, iova, 0)) {
		dev_err_ratelimited(ctx->dev,
				    "Unhandled context fault: fsr=0x%x, "
				    "iova=0x%016llx, fsynr=0x%x, cb=%d\n",
				    fsr, iova, fsynr, ctx->asid);
	}

	iommu_writel(ctx, ARM_SMMU_CB_FSR, fsr);
	iommu_writel(ctx, ARM_SMMU_CB_RESUME, ARM_SMMU_RESUME_TERMINATE);

	return IRQ_HANDLED;
}

static int qcom_iommu_init_domain(struct iommu_domain *domain,
				  struct qcom_iommu_dev *qcom_iommu,
				  struct device *dev)
{
	struct qcom_iommu_domain *qcom_domain = to_qcom_iommu_domain(domain);
	struct iommu_fwspec *fwspec = dev_iommu_fwspec_get(dev);
	struct io_pgtable_ops *pgtbl_ops;
	struct io_pgtable_cfg pgtbl_cfg;
	int i, ret = 0;
	u32 reg;

	if (qcom_iommu->msm8992)
		dev_info(qcom_iommu->dev, "MSM8992 GPU domain attach: %s, %u contexts\n",
			dev_name(dev), fwspec->num_ids);

	mutex_lock(&qcom_domain->init_mutex);
	if (qcom_domain->iommu)
		goto out_unlock;

	pgtbl_cfg = (struct io_pgtable_cfg) {
		.pgsize_bitmap	= qcom_iommu_ops.pgsize_bitmap,
		.ias		= 32,
		.oas		= 40,
		.tlb		= &qcom_flush_ops,
		.iommu_dev	= qcom_iommu->dev,
	};

	qcom_domain->iommu = qcom_iommu;
	qcom_domain->fwspec = fwspec;

	pgtbl_ops = alloc_io_pgtable_ops(ARM_32_LPAE_S1, &pgtbl_cfg, qcom_domain);
	if (!pgtbl_ops) {
		dev_err(qcom_iommu->dev, "failed to allocate pagetable ops\n");
		ret = -ENOMEM;
		goto out_clear_iommu;
	}

	/* Update the domain's page sizes to reflect the page table format */
	domain->pgsize_bitmap = pgtbl_cfg.pgsize_bitmap;
	domain->geometry.aperture_end = (1ULL << pgtbl_cfg.ias) - 1;
	domain->geometry.force_aperture = true;

	for (i = 0; i < fwspec->num_ids; i++) {
		struct qcom_iommu_ctx *ctx = to_ctx(qcom_domain, fwspec->ids[i]);

		if (!ctx->secure_init) {
			/* MSM8992 runtime resume already restores the global config. */
			if (!qcom_iommu->msm8992) {
				ret = qcom_scm_restore_sec_cfg(qcom_iommu->sec_id, ctx->asid);
				if (ret) {
					dev_err(qcom_iommu->dev, "secure init failed: %d\n", ret);
					goto out_clear_iommu;
				}
			}
			ctx->secure_init = true;
		}

		/* Secured QSMMU-500/QSMMU-v2 contexts cannot be programmed */
		if (ctx->secured_ctx) {
			ctx->domain = domain;
			continue;
		}

		ctx->ttbr0 = pgtbl_cfg.arm_lpae_s1_cfg.ttbr |
			FIELD_PREP(ARM_SMMU_TTBRn_ASID, ctx->asid);
		if (qcom_iommu->msm8992) {
			ctx->tcr = qcom_iommu_msm8992_tcr(&pgtbl_cfg);
			ctx->tcr2 = 0;
		} else {
			ctx->tcr = arm_smmu_lpae_tcr(&pgtbl_cfg) | ARM_SMMU_TCR_EAE;
			ctx->tcr2 = arm_smmu_lpae_tcr2(&pgtbl_cfg);
		}
		ctx->mair0 = pgtbl_cfg.arm_lpae_s1_cfg.mair;
		ctx->mair1 = pgtbl_cfg.arm_lpae_s1_cfg.mair >> 32;

		/* SCTLR */
		reg = ARM_SMMU_SCTLR_CFIE | ARM_SMMU_SCTLR_CFRE |
		      ARM_SMMU_SCTLR_AFE | ARM_SMMU_SCTLR_TRE |
		      ARM_SMMU_SCTLR_M | ARM_SMMU_SCTLR_S1_ASIDPNE |
		      ARM_SMMU_SCTLR_CFCFG;

		if (IS_ENABLED(CONFIG_CPU_BIG_ENDIAN))
			reg |= ARM_SMMU_SCTLR_E;

		ctx->sctlr = reg;
		ctx->domain = domain;
		/* Publish the handler's domain before enabling context fault IRQs. */
		wmb();
		qcom_iommu_program_context(ctx, qcom_iommu->msm8992);
		if (qcom_iommu->msm8992)
			dev_info(qcom_iommu->dev, "MSM8992 GPU context %u enabled: TTBR=%#llx TCR=%#x\n",
				ctx->asid, ctx->ttbr0, ctx->tcr);
	}

	mutex_unlock(&qcom_domain->init_mutex);

	/* Publish page table ops for map/unmap */
	qcom_domain->pgtbl_ops = pgtbl_ops;

	return 0;

out_clear_iommu:
	qcom_domain->iommu = NULL;
out_unlock:
	mutex_unlock(&qcom_domain->init_mutex);
	return ret;
}

static struct iommu_domain *qcom_iommu_domain_alloc_paging(struct device *dev)
{
	struct qcom_iommu_domain *qcom_domain;

	/*
	 * Allocate the domain and initialise some of its data structures.
	 * We can't really do anything meaningful until we've added a
	 * master.
	 */
	qcom_domain = kzalloc(sizeof(*qcom_domain), GFP_KERNEL);
	if (!qcom_domain)
		return NULL;

	mutex_init(&qcom_domain->init_mutex);
	spin_lock_init(&qcom_domain->pgtbl_lock);

	return &qcom_domain->domain;
}

static void qcom_iommu_domain_free(struct iommu_domain *domain)
{
	struct qcom_iommu_domain *qcom_domain = to_qcom_iommu_domain(domain);

	if (qcom_domain->iommu) {
		/*
		 * NOTE: unmap can be called after client device is powered
		 * off, for example, with GPUs or anything involving dma-buf.
		 * So we cannot rely on the device_link.  Make sure the IOMMU
		 * is on to avoid unclocked accesses in the TLB inv path:
		 */
		pm_runtime_get_sync(qcom_domain->iommu->dev);
		free_io_pgtable_ops(qcom_domain->pgtbl_ops);
		pm_runtime_put_sync(qcom_domain->iommu->dev);
	}

	kfree(qcom_domain);
}

static int qcom_iommu_attach_dev(struct iommu_domain *domain, struct device *dev)
{
	struct qcom_iommu_dev *qcom_iommu = dev_iommu_priv_get(dev);
	struct qcom_iommu_domain *qcom_domain = to_qcom_iommu_domain(domain);
	int ret;

	if (!qcom_iommu) {
		dev_err(dev, "cannot attach to IOMMU, is it on the same bus?\n");
		return -ENXIO;
	}

	/* Ensure that the domain is finalized */
	ret = pm_runtime_resume_and_get(qcom_iommu->dev);
	if (ret < 0)
		return ret;
	ret = qcom_iommu_init_domain(domain, qcom_iommu, dev);
	pm_runtime_put_sync(qcom_iommu->dev);
	if (ret < 0)
		return ret;

	/*
	 * Sanity check the domain. We don't support domains across
	 * different IOMMUs.
	 */
	if (qcom_domain->iommu != qcom_iommu)
		return -EINVAL;

	return 0;
}

static int qcom_iommu_identity_attach(struct iommu_domain *identity_domain,
				      struct device *dev)
{
	struct iommu_domain *domain = iommu_get_domain_for_dev(dev);
	struct qcom_iommu_domain *qcom_domain;
	struct iommu_fwspec *fwspec = dev_iommu_fwspec_get(dev);
	struct qcom_iommu_dev *qcom_iommu = dev_iommu_priv_get(dev);
	unsigned int i;

	if (domain == identity_domain || !domain)
		return 0;

	qcom_domain = to_qcom_iommu_domain(domain);
	if (WARN_ON(!qcom_domain->iommu))
		return -EINVAL;

	pm_runtime_get_sync(qcom_iommu->dev);
	for (i = 0; i < fwspec->num_ids; i++) {
		struct qcom_iommu_ctx *ctx = to_ctx(qcom_domain, fwspec->ids[i]);

		/* Disable the context bank: */
		iommu_writel(ctx, ARM_SMMU_CB_SCTLR, 0);

		ctx->domain = NULL;
		ctx->sctlr = 0;
	}
	pm_runtime_put_sync(qcom_iommu->dev);
	return 0;
}

static struct iommu_domain_ops qcom_iommu_identity_ops = {
	.attach_dev = qcom_iommu_identity_attach,
};

static struct iommu_domain qcom_iommu_identity_domain = {
	.type = IOMMU_DOMAIN_IDENTITY,
	.ops = &qcom_iommu_identity_ops,
};

static int qcom_iommu_map(struct iommu_domain *domain, unsigned long iova,
			  phys_addr_t paddr, size_t pgsize, size_t pgcount,
			  int prot, gfp_t gfp, size_t *mapped)
{
	int ret;
	unsigned long flags;
	struct qcom_iommu_domain *qcom_domain = to_qcom_iommu_domain(domain);
	struct io_pgtable_ops *ops = qcom_domain->pgtbl_ops;

	if (!ops)
		return -ENODEV;

	spin_lock_irqsave(&qcom_domain->pgtbl_lock, flags);
	ret = ops->map_pages(ops, iova, paddr, pgsize, pgcount, prot, GFP_ATOMIC, mapped);
	spin_unlock_irqrestore(&qcom_domain->pgtbl_lock, flags);
	return ret;
}

static size_t qcom_iommu_unmap(struct iommu_domain *domain, unsigned long iova,
			       size_t pgsize, size_t pgcount,
			       struct iommu_iotlb_gather *gather)
{
	size_t ret;
	unsigned long flags;
	struct qcom_iommu_domain *qcom_domain = to_qcom_iommu_domain(domain);
	struct io_pgtable_ops *ops = qcom_domain->pgtbl_ops;

	if (!ops)
		return 0;

	/* NOTE: unmap can be called after client device is powered off,
	 * for example, with GPUs or anything involving dma-buf.  So we
	 * cannot rely on the device_link.  Make sure the IOMMU is on to
	 * avoid unclocked accesses in the TLB inv path:
	 */
	pm_runtime_get_sync(qcom_domain->iommu->dev);
	spin_lock_irqsave(&qcom_domain->pgtbl_lock, flags);
	ret = ops->unmap_pages(ops, iova, pgsize, pgcount, gather);
	spin_unlock_irqrestore(&qcom_domain->pgtbl_lock, flags);
	pm_runtime_put_sync(qcom_domain->iommu->dev);

	return ret;
}

static void qcom_iommu_flush_iotlb_all(struct iommu_domain *domain)
{
	struct qcom_iommu_domain *qcom_domain = to_qcom_iommu_domain(domain);
	struct io_pgtable *pgtable = container_of(qcom_domain->pgtbl_ops,
						  struct io_pgtable, ops);
	if (!qcom_domain->pgtbl_ops)
		return;

	pm_runtime_get_sync(qcom_domain->iommu->dev);
	qcom_iommu_tlb_sync(pgtable->cookie);
	pm_runtime_put_sync(qcom_domain->iommu->dev);
}

static void qcom_iommu_iotlb_sync(struct iommu_domain *domain,
				  struct iommu_iotlb_gather *gather)
{
	qcom_iommu_flush_iotlb_all(domain);
}

static phys_addr_t qcom_iommu_iova_to_phys(struct iommu_domain *domain,
					   dma_addr_t iova)
{
	phys_addr_t ret;
	unsigned long flags;
	struct qcom_iommu_domain *qcom_domain = to_qcom_iommu_domain(domain);
	struct io_pgtable_ops *ops = qcom_domain->pgtbl_ops;

	if (!ops)
		return 0;

	spin_lock_irqsave(&qcom_domain->pgtbl_lock, flags);
	ret = ops->iova_to_phys(ops, iova);
	spin_unlock_irqrestore(&qcom_domain->pgtbl_lock, flags);

	return ret;
}

static bool qcom_iommu_capable(struct device *dev, enum iommu_cap cap)
{
	switch (cap) {
	case IOMMU_CAP_CACHE_COHERENCY:
		/*
		 * Return true here as the SMMU can always send out coherent
		 * requests.
		 */
		return true;
	case IOMMU_CAP_NOEXEC:
		return true;
	default:
		return false;
	}
}

static struct iommu_device *qcom_iommu_probe_device(struct device *dev)
{
	struct qcom_iommu_dev *qcom_iommu = dev_iommu_priv_get(dev);
	struct device_link *link;

	if (!qcom_iommu)
		return ERR_PTR(-ENODEV);

	/*
	 * Establish the link between iommu and master, so that the
	 * iommu gets runtime enabled/disabled as per the master's
	 * needs.
	 */
	link = device_link_add(dev, qcom_iommu->dev, DL_FLAG_PM_RUNTIME);
	if (!link) {
		dev_err(qcom_iommu->dev, "Unable to create device link between %s and %s\n",
			dev_name(qcom_iommu->dev), dev_name(dev));
		return ERR_PTR(-ENODEV);
	}

	return &qcom_iommu->iommu;
}

static int qcom_iommu_of_xlate(struct device *dev,
			       const struct of_phandle_args *args)
{
	struct qcom_iommu_dev *qcom_iommu;
	struct platform_device *iommu_pdev;
	unsigned asid = args->args[0];

	if (args->args_count != 1) {
		dev_err(dev, "incorrect number of iommu params found for %s "
			"(found %d, expected 1)\n",
			args->np->full_name, args->args_count);
		return -EINVAL;
	}

	iommu_pdev = of_find_device_by_node(args->np);
	if (WARN_ON(!iommu_pdev))
		return -EINVAL;

	qcom_iommu = platform_get_drvdata(iommu_pdev);

	put_device(&iommu_pdev->dev);

	/* make sure the asid specified in dt is valid, so we don't have
	 * to sanity check this elsewhere:
	 */
	if (WARN_ON(asid > qcom_iommu->max_asid) ||
	    WARN_ON(qcom_iommu->ctxs[asid] == NULL))
		return -EINVAL;

	if (!dev_iommu_priv_get(dev)) {
		dev_iommu_priv_set(dev, qcom_iommu);
	} else {
		/* make sure devices iommus dt node isn't referring to
		 * multiple different iommu devices.  Multiple context
		 * banks are ok, but multiple devices are not:
		 */
		if (WARN_ON(qcom_iommu != dev_iommu_priv_get(dev)))
			return -EINVAL;
	}

	return iommu_fwspec_add_ids(dev, &asid, 1);
}

static const struct iommu_ops qcom_iommu_ops = {
	.identity_domain = &qcom_iommu_identity_domain,
	.capable	= qcom_iommu_capable,
	.domain_alloc_paging = qcom_iommu_domain_alloc_paging,
	.probe_device	= qcom_iommu_probe_device,
	.device_group	= generic_device_group,
	.of_xlate	= qcom_iommu_of_xlate,
	.pgsize_bitmap	= SZ_4K | SZ_64K | SZ_1M | SZ_16M,
	.default_domain_ops = &(const struct iommu_domain_ops) {
		.attach_dev	= qcom_iommu_attach_dev,
		.map_pages	= qcom_iommu_map,
		.unmap_pages	= qcom_iommu_unmap,
		.flush_iotlb_all = qcom_iommu_flush_iotlb_all,
		.iotlb_sync	= qcom_iommu_iotlb_sync,
		.iova_to_phys	= qcom_iommu_iova_to_phys,
		.free		= qcom_iommu_domain_free,
	}
};

static int qcom_iommu_sec_ptbl_init(struct device *dev, bool msm8992)
{
	size_t psize = 0;
	unsigned int spare = 0;
	void *cpu_addr;
	dma_addr_t paddr;
	unsigned long attrs;
	static bool allocated = false;
	int ret;

	if (allocated)
		return 0;
	if (msm8992) {
		/* OEM msm_iommu_sec.c reserves a 300MiB virtual CP window. */
		ret = qcom_scm_iommu_set_cp_pool_size(0, 300 * SZ_1M);
		if (ret)
			return dev_err_probe(dev, ret, "MSM8992 IOMMU CP pool setup failed\n");
	}

	ret = qcom_scm_iommu_secure_ptbl_size(spare, &psize);
	if (ret) {
		dev_err(dev, "failed to get iommu secure pgtable size (%d)\n",
			ret);
		return ret;
	}

	dev_info(dev, "iommu sec: pgtable size: %zu\n", psize);

	attrs = DMA_ATTR_NO_KERNEL_MAPPING;

	cpu_addr = dma_alloc_attrs(dev, psize, &paddr, GFP_KERNEL, attrs);
	if (!cpu_addr) {
		dev_err(dev, "failed to allocate %zu bytes for pgtable\n",
			psize);
		return -ENOMEM;
	}

	ret = qcom_scm_iommu_secure_ptbl_init(paddr, psize, spare);
	if (ret) {
		dev_err(dev, "failed to init iommu pgtable (%d)\n", ret);
		goto free_mem;
	}

	allocated = true;
	return 0;

free_mem:
	dma_free_attrs(dev, psize, cpu_addr, paddr, attrs);
	return ret;
}

static int get_asid(const struct device_node *np)
{
	u32 reg, val;
	int asid;

	/* read the "reg" property directly to get the relative address
	 * of the context bank, and calculate the asid from that:
	 */
	if (of_property_read_u32_index(np, "reg", 0, &reg))
		return -ENODEV;

	/*
	 * Context banks are 0x1000 apart but, in some cases, the ASID
	 * number doesn't match to this logic and needs to be passed
	 * from the DT configuration explicitly.
	 */
	if (!of_property_read_u32(np, "qcom,ctx-asid", &val))
		asid = val;
	else
		asid = reg / 0x1000;

	return asid;
}

static int qcom_iommu_ctx_probe(struct platform_device *pdev)
{
	struct qcom_iommu_ctx *ctx;
	struct device *dev = &pdev->dev;
	struct qcom_iommu_dev *qcom_iommu = dev_get_drvdata(dev->parent);
	int ret, irq;

	ctx = devm_kzalloc(dev, sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;

	ctx->dev = dev;
	platform_set_drvdata(pdev, ctx);

	ctx->base = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(ctx->base))
		return PTR_ERR(ctx->base);

	irq = platform_get_irq(pdev, 0);
	if (irq < 0)
		return irq;

	if (of_device_is_compatible(dev->of_node, "qcom,msm-iommu-v2-sec"))
		ctx->secured_ctx = true;

	/* clear IRQs before registering fault handler, just in case the
	 * boot-loader left us a surprise:
	 */
	if (!ctx->secured_ctx)
		iommu_writel(ctx, ARM_SMMU_CB_FSR, iommu_readl(ctx, ARM_SMMU_CB_FSR));

	ret = devm_request_irq(dev, irq,
			       qcom_iommu_fault,
			       IRQF_SHARED,
			       "qcom-iommu-fault",
			       ctx);
	if (ret) {
		dev_err(dev, "failed to request IRQ %u\n", irq);
		return ret;
	}

	ret = get_asid(dev->of_node);
	if (ret < 0) {
		dev_err(dev, "missing reg property\n");
		return ret;
	}

	ctx->asid = ret;

	dev_dbg(dev, "found asid %u\n", ctx->asid);

	qcom_iommu->ctxs[ctx->asid] = ctx;

	return 0;
}

static void qcom_iommu_ctx_remove(struct platform_device *pdev)
{
	struct qcom_iommu_dev *qcom_iommu = dev_get_drvdata(pdev->dev.parent);
	struct qcom_iommu_ctx *ctx = platform_get_drvdata(pdev);

	platform_set_drvdata(pdev, NULL);

	qcom_iommu->ctxs[ctx->asid] = NULL;
}

static const struct of_device_id ctx_of_match[] = {
	{ .compatible = "qcom,msm-iommu-v1-ns" },
	{ .compatible = "qcom,msm-iommu-v1-sec" },
	{ .compatible = "qcom,msm-iommu-v2-ns" },
	{ .compatible = "qcom,msm-iommu-v2-sec" },
	{ /* sentinel */ }
};

static struct platform_driver qcom_iommu_ctx_driver = {
	.driver	= {
		.name		= "qcom-iommu-ctx",
		.of_match_table	= ctx_of_match,
	},
	.probe	= qcom_iommu_ctx_probe,
	.remove_new = qcom_iommu_ctx_remove,
};

static bool qcom_iommu_has_secure_context(struct qcom_iommu_dev *qcom_iommu)
{
	struct device_node *child;

	for_each_child_of_node(qcom_iommu->dev->of_node, child) {
		if (of_device_is_compatible(child, "qcom,msm-iommu-v1-sec") ||
		    of_device_is_compatible(child, "qcom,msm-iommu-v2-sec")) {
			of_node_put(child);
			return true;
		}
	}

	return false;
}

static int qcom_iommu_device_probe(struct platform_device *pdev)
{
	struct device_node *child;
	struct qcom_iommu_dev *qcom_iommu;
	struct device *dev = &pdev->dev;
	struct resource *res;
	struct clk *clk;
	int ret, max_asid = 0;
	bool msm8992 = of_device_is_compatible(dev->of_node, "qcom,msm8992-iommu");

	if (msm8992 && !msm8992_probe) {
		dev_info(dev, "MSM8992 GPU IOMMU held for manual activation\n");
		return -ENODEV;
	}

	/* find the max asid (which is 1:1 to ctx bank idx), so we know how
	 * many child ctx devices we have:
	 */
	for_each_child_of_node(dev->of_node, child)
		max_asid = max(max_asid, get_asid(child));

	qcom_iommu = devm_kzalloc(dev, struct_size(qcom_iommu, ctxs, max_asid + 1),
				  GFP_KERNEL);
	if (!qcom_iommu)
		return -ENOMEM;
	qcom_iommu->max_asid = max_asid;
	qcom_iommu->dev = dev;
	qcom_iommu->msm8992 = msm8992;
	if (msm8992) {
		struct dev_pm_domain_list *domains;
		int corner;

		ret = devm_pm_domain_attach_list(dev, NULL, &domains);
		if (ret < 0)
			return dev_err_probe(dev, ret, "MSM8992 GPU domain attachment failed\n");
		if (ret != 2)
			return dev_err_probe(dev, -EINVAL, "MSM8992 GPU needs two domains, got %d\n", ret);
		corner = of_get_required_opp_performance_state(dev->of_node, 0);
		if (corner < 0)
			return dev_err_probe(dev, corner, "MSM8992 GPU initial RPM corner lookup failed\n");
		ret = dev_pm_genpd_set_performance_state(domains->pd_devs[0], corner);
		if (ret)
			return dev_err_probe(dev, ret, "MSM8992 GPU RPM corner %d vote failed\n", corner);
	}

	res = platform_get_resource(pdev, IORESOURCE_MEM, 0);
	if (res) {
		qcom_iommu->local_base = devm_ioremap_resource(dev, res);
		if (IS_ERR(qcom_iommu->local_base))
			return PTR_ERR(qcom_iommu->local_base);
	}

	clk = devm_clk_get(dev, "iface");
	if (IS_ERR(clk)) {
		dev_err(dev, "failed to get iface clock\n");
		return PTR_ERR(clk);
	}
	qcom_iommu->clks[CLK_IFACE].clk = clk;

	clk = devm_clk_get(dev, "bus");
	if (IS_ERR(clk)) {
		dev_err(dev, "failed to get bus clock\n");
		return PTR_ERR(clk);
	}
	qcom_iommu->clks[CLK_BUS].clk = clk;
	if (msm8992) {
		ret = clk_set_rate(clk, 180000000);
		if (ret)
			return dev_err_probe(dev, ret, "MSM8992 GPU bus clock 180MHz setup failed\n");
	}

	clk = devm_clk_get_optional(dev, "tbu");
	if (IS_ERR(clk)) {
		dev_err(dev, "failed to get tbu clock\n");
		return PTR_ERR(clk);
	}
	qcom_iommu->clks[CLK_TBU].clk = clk;

	if (of_property_read_u32(dev->of_node, "qcom,iommu-secure-id",
				 &qcom_iommu->sec_id)) {
		dev_err(dev, "missing qcom,iommu-secure-id property\n");
		return -ENODEV;
	}

	if (msm8992 || qcom_iommu_has_secure_context(qcom_iommu)) {
		/* Firmware needs the global table even for our nonsecure context. */
		ret = qcom_iommu_sec_ptbl_init(dev, msm8992);
		if (ret) {
			dev_err(dev, "cannot init secure pg table(%d)\n", ret);
			return ret;
		}
	}

	platform_set_drvdata(pdev, qcom_iommu);

	if (msm8992) {
		/* Clear a previous probe's runtime error before a fresh attempt. */
		ret = pm_runtime_set_suspended(dev);
		if (ret)
			return ret;
	}
	pm_runtime_enable(dev);
	/* Context probe touches MMIO, so keep the new GPU domain powered. */
	if (msm8992) {
		ret = pm_runtime_resume_and_get(dev);
		if (ret < 0) {
			dev_err(dev, "MSM8992 GPU power/clock resume failed: %d\n", ret);
			goto err_pm_disable;
		}
	}

	/* register context bank devices, which are child nodes: */
	ret = devm_of_platform_populate(dev);
	if (ret) {
		dev_err(dev, "Failed to populate iommu contexts\n");
		goto err_pm_disable;
	}

	ret = iommu_device_sysfs_add(&qcom_iommu->iommu, dev, NULL,
				     dev_name(dev));
	if (ret) {
		dev_err(dev, "Failed to register iommu in sysfs\n");
		goto err_pm_disable;
	}

	ret = iommu_device_register(&qcom_iommu->iommu, &qcom_iommu_ops, dev);
	if (ret) {
		dev_err(dev, "Failed to register iommu\n");
		goto err_sysfs_remove;
	}

	if (msm8992) {
		dev_info(dev, "MSM8992 GPU IOMMU ready: OEM context 0, secure ID 18\n");
		pm_runtime_put_sync(dev);
	} else if (qcom_iommu->local_base) {
		pm_runtime_get_sync(dev);
		writel_relaxed(0xffffffff, qcom_iommu->local_base + SMMU_INTR_SEL_NS);
		pm_runtime_put_sync(dev);
	}

	return 0;

err_sysfs_remove:
	iommu_device_sysfs_remove(&qcom_iommu->iommu);
err_pm_disable:
	if (msm8992 && pm_runtime_active(dev))
		pm_runtime_put_sync(dev);
	pm_runtime_disable(dev);
	return ret;
}

static void qcom_iommu_device_remove(struct platform_device *pdev)
{
	struct qcom_iommu_dev *qcom_iommu = platform_get_drvdata(pdev);

	pm_runtime_force_suspend(&pdev->dev);
	platform_set_drvdata(pdev, NULL);
	iommu_device_sysfs_remove(&qcom_iommu->iommu);
	iommu_device_unregister(&qcom_iommu->iommu);
}

static int __maybe_unused qcom_iommu_resume(struct device *dev)
{
	struct qcom_iommu_dev *qcom_iommu = dev_get_drvdata(dev);
	int ret;

	ret = clk_bulk_prepare_enable(CLK_NUM, qcom_iommu->clks);
	if (ret < 0)
		return ret;
	if (qcom_iommu->msm8992) {
		struct qcom_iommu_ctx *ctx = qcom_iommu->ctxs[0];

		ret = qcom_scm_restore_sec_cfg(qcom_iommu->sec_id, 0);
		if (ret) {
			dev_err(dev, "MSM8992 GPU secure configuration ID %u failed: %d\n",
				qcom_iommu->sec_id, ret);
			clk_bulk_disable_unprepare(CLK_NUM, qcom_iommu->clks);
			return ret;
		}
		qcom_iommu_msm8992_bfb(qcom_iommu);
		if (ctx && ctx->domain && ctx->sctlr)
			qcom_iommu_program_context(ctx, true);
		return 0;
	}

	if (dev->pm_domain)
		return qcom_scm_restore_sec_cfg(qcom_iommu->sec_id, 0);

	return ret;
}

static int __maybe_unused qcom_iommu_suspend(struct device *dev)
{
	struct qcom_iommu_dev *qcom_iommu = dev_get_drvdata(dev);

	clk_bulk_disable_unprepare(CLK_NUM, qcom_iommu->clks);

	return 0;
}

static const struct dev_pm_ops qcom_iommu_pm_ops = {
	SET_RUNTIME_PM_OPS(qcom_iommu_suspend, qcom_iommu_resume, NULL)
	SET_SYSTEM_SLEEP_PM_OPS(pm_runtime_force_suspend,
				pm_runtime_force_resume)
};

static const struct of_device_id qcom_iommu_of_match[] = {
	{ .compatible = "qcom,msm-iommu-v1" },
	{ .compatible = "qcom,msm-iommu-v2" },
	{ /* sentinel */ }
};

static struct platform_driver qcom_iommu_driver = {
	.driver	= {
		.name		= "qcom-iommu",
		.of_match_table	= qcom_iommu_of_match,
		.pm		= &qcom_iommu_pm_ops,
	},
	.probe	= qcom_iommu_device_probe,
	.remove_new = qcom_iommu_device_remove,
};

static int __init qcom_iommu_init(void)
{
	int ret;

	ret = platform_driver_register(&qcom_iommu_ctx_driver);
	if (ret)
		return ret;

	ret = platform_driver_register(&qcom_iommu_driver);
	if (ret)
		platform_driver_unregister(&qcom_iommu_ctx_driver);

	return ret;
}
device_initcall(qcom_iommu_init);
