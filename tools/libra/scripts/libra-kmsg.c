/* SPDX-License-Identifier: GPL-2.0-only */
/* Built with tools/include/nolibc: no host glibc dependency in the initrd. */

static char record[65537];

static int create_log_parents(const char *filename)
{
	char path[4096];
	size_t i, len = strlen(filename);

	if (len >= sizeof(path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	memcpy(path, filename, len + 1);
	for (i = 1; i < len; i++) {
		if (path[i] != '/')
			continue;
		path[i] = 0;
		if (mkdir(path, 0755) < 0 && errno != EEXIST)
			return -1;
		path[i] = '/';
	}
	return 0;
}

static int write_all(int fd, const char *buf, size_t count)
{
	while (count) {
		ssize_t n = write(fd, buf, count);

		if (n < 0 && errno == EINTR)
			continue;
		if (n <= 0)
			return -1;
		buf += n;
		count -= n;
	}
	return 0;
}

static void print_record(char *buf)
{
	char *first = strchr(buf, ',');
	char *body = strchr(buf, ';');
	char *end, fraction[7];
	unsigned long long sequence, usec, remainder;
	int i;

	if (!first || !body) {
		printf("%s", buf);
		return;
	}
	sequence = strtoull(first + 1, &end, 10);
	if (*end != ',') {
		printf("%s", buf);
		return;
	}
	usec = strtoull(end + 1, &end, 10);
	if (*end != ',') {
		printf("%s", buf);
		return;
	}
	remainder = usec % 1000000;
	fraction[6] = 0;
	for (i = 5; i >= 0; i--) {
		fraction[i] = '0' + remainder % 10;
		remainder /= 10;
	}
	printf("[%llu.%s #%llu] %s", usec / 1000000, fraction,
	       sequence, body + 1);
}

int main(int argc, char **argv)
{
	struct pollfd event;
	int fd, logfile, status = 0, done = 0;
	pid_t child;

	if (argc < 3 || argv[2][0] != '/') {
		fprintf(stderr, "Usage: libra-kmsg LOGFILE /absolute/command [args...]\n");
		return 2;
	}
	fd = open("/dev/kmsg", O_RDONLY | O_NONBLOCK | O_CLOEXEC, 0);
	if (fd < 0 || lseek(fd, 0, SEEK_END) < 0) {
		perror("libra-kmsg: seek to kernel log end");
		return 1;
	}
	if (create_log_parents(argv[1]) < 0) {
		perror("libra-kmsg: create capture directory");
		return 1;
	}
	logfile = open(argv[1], O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
	if (logfile < 0) {
		perror("libra-kmsg: open capture file");
		return 1;
	}
	/* Establish the record cursor before the command can produce messages. */
	child = fork();
	if (child < 0) {
		perror("libra-kmsg: fork");
		return 1;
	}
	if (!child) {
		close(fd);
		close(logfile);
		execve(argv[2], argv + 2, environ);
		perror("libra-kmsg: exec command");
		exit(127);
	}
	event.fd = fd;
	event.events = POLLIN;
	for (;;) {
		ssize_t n;
		pid_t waited;

		if (!done) {
			waited = waitpid(child, &status, WNOHANG);
			if (waited == child)
				done = 1;
			else if (waited < 0 && errno != EINTR) {
				perror("libra-kmsg: wait for command");
				return 1;
			}
		}
		n = read(fd, record, sizeof(record) - 1);
		if (n > 0) {
			record[n] = 0;
			if (write_all(logfile, record, n) < 0) {
				perror("libra-kmsg: save record");
				return 1;
			}
			print_record(record);
			continue;
		}
		if (n < 0 && errno == EPIPE) {
			fprintf(stderr, "libra-kmsg: kernel log overrun; records lost\n");
			continue;
		}
		if (n < 0 && errno == EINTR)
			continue;
		if (n < 0 && errno != EAGAIN) {
			perror("libra-kmsg: read kernel record");
			return 1;
		}
		if (done)
			break;
		if (poll(&event, 1, 100) < 0 && errno != EINTR) {
			perror("libra-kmsg: poll kernel log");
			return 1;
		}
	}
	close(logfile);
	close(fd);
	if (WIFEXITED(status))
		return WEXITSTATUS(status);
	return 128 + WTERMSIG(status);
}
