/* SPDX-License-Identifier: GPL-2.0-only */
/* Open triggers microcode loading and CP_ME_INIT; no userspace shader yet. */
#ifndef _NOLIBC_H
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>
#endif
#include <drm/msm_drm.h>

int main(void)
{
	const struct { uint32_t id; const char *name; } params[] = {
		{ MSM_PARAM_GPU_ID, "GPU_ID" },
		{ MSM_PARAM_GMEM_SIZE, "GMEM_SIZE" },
		{ MSM_PARAM_CHIP_ID, "CHIP_ID" },
		{ MSM_PARAM_MAX_FREQ, "MAX_FREQ" },
	};
	int fd = open("/dev/dri/renderD128", O_RDWR | O_CLOEXEC);
	unsigned int i;

	if (fd < 0) {
		perror("open renderD128");
		return 1;
	}
	for (i = 0; i < sizeof(params) / sizeof(params[0]); i++) {
		struct drm_msm_param p = { .pipe = MSM_PIPE_3D0, .param = params[i].id };

		if (ioctl(fd, DRM_IOCTL_MSM_GET_PARAM, &p)) {
			fprintf(stderr, "%s: errno=%d\n", params[i].name, errno);
			close(fd);
			return 1;
		}
		printf("%s=%llu\n", params[i].name, (unsigned long long)p.value);
		if ((p.param == MSM_PARAM_GPU_ID && p.value != 418) ||
		    (p.param == MSM_PARAM_GMEM_SIZE && p.value != 524288) ||
		    (p.param == MSM_PARAM_MAX_FREQ && p.value != 300000000)) {
			close(fd);
			return 1;
		}
	}
	close(fd);
	return 0;
}
