## 操作rootfs的规范

- 禁止将rootfs文件直接写到文件夹
- 你必须对不同的发行版创建不同的img，操作时将对应img挂载到rootfs/
- 构建rootfs时必须将正常情况下需要安装的包都装进rootfs内，包括但不限于systemd、包管理器等
- 内核镜像格式f2fs

## 操作内核的规范

- 此内核的编译目标是aarch64
- 修改配置时禁止动defconfig
- 编译完成一遍之后，必须复用原有的编译产物
- 在cfg内删除一切不必要的配置，包括*AMD*、*intel*、*nvidia*、其他vendor的dtb等
- 打开f2fs相关支持

## 操作本机的规范

- 这是wsl环境，可以直接sudo