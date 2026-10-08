/* SPDX-License-Identifier: GPL-2.0-only */
/* Surfaceless GLES2 shader submission and pixel readback. */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <stdio.h>
#include <string.h>

static GLuint shader(GLenum type, const char *source)
{
	GLuint s = glCreateShader(type);
	GLint ok;
	char log[2048];
	glShaderSource(s, 1, &source, NULL);
	glCompileShader(s);
	glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
	if (!ok) {
		glGetShaderInfoLog(s, sizeof(log), NULL, log);
		fprintf(stderr, "shader: %s\n", log);
		return 0;
	}
	return s;
}

int main(int argc, char **argv)
{
	const EGLint attribs[] = { EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
		EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT, EGL_RED_SIZE, 8,
		EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE };
	const EGLint size[] = { EGL_WIDTH, 64, EGL_HEIGHT, 64, EGL_NONE };
	const EGLint context[] = { EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE };
	const GLfloat vertices[] = { -1, -1, 1, -1, 0, 1 };
	EGLDisplay d = eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, NULL);
	EGLConfig config;
	EGLContext c;
	EGLSurface s;
	EGLint n;
	GLuint vs, fs, program;
	GLint ok;
	GLubyte center[4], corner[4];
	const char *renderer;
	const char *phase = "display/config";
	int allow_software = argc == 2 && !strcmp(argv[1], "--allow-software");
	setvbuf(stdout, NULL, _IONBF, 0);

	if (d == EGL_NO_DISPLAY || !eglInitialize(d, NULL, NULL) ||
	    !eglChooseConfig(d, attribs, &config, 1, &n) || !n ||
	    !eglBindAPI(EGL_OPENGL_ES_API))
		goto egl_error;
	phase = "context/pbuffer";
	c = eglCreateContext(d, config, EGL_NO_CONTEXT, context);
	s = eglCreatePbufferSurface(d, config, size);
	if (c == EGL_NO_CONTEXT || s == EGL_NO_SURFACE || !eglMakeCurrent(d, s, s, c))
		goto egl_error;
	renderer = (const char *)glGetString(GL_RENDERER);
	printf("GL_RENDERER=%s\n", renderer ? renderer : "null");
	if (!renderer || (!allow_software && !strstr(renderer, "FD418"))) {
		fprintf(stderr, "Expected the real FD418 renderer\n");
		return 1;
	}
	vs = shader(GL_VERTEX_SHADER, "attribute vec2 p; void main(){gl_Position=vec4(p,0.0,1.0);}");
	fs = shader(GL_FRAGMENT_SHADER, "precision mediump float; void main(){gl_FragColor=vec4(1.0,0.25,0.0,1.0);}");
	if (!vs || !fs)
		return 1;
	program = glCreateProgram();
	glAttachShader(program, vs);
	glAttachShader(program, fs);
	glBindAttribLocation(program, 0, "p");
	glLinkProgram(program);
	glGetProgramiv(program, GL_LINK_STATUS, &ok);
	if (!ok) {
		fprintf(stderr, "program link failed\n");
		return 1;
	}
	glViewport(0, 0, 64, 64);
	glDisable(GL_DITHER);
	glClearColor(0.0, 0.125, 0.5, 1.0);
	glClear(GL_COLOR_BUFFER_BIT);
	glUseProgram(program);
	glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, vertices);
	glEnableVertexAttribArray(0);
	puts("Submitting triangle and reading pixels");
	glDrawArrays(GL_TRIANGLES, 0, 3);
	glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, center);
	glReadPixels(0, 63, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, corner);
	printf("center=%u,%u,%u,%u corner=%u,%u,%u,%u\n",
		center[0], center[1], center[2], center[3], corner[0], corner[1], corner[2], corner[3]);
	if (glGetError() != GL_NO_ERROR || center[0] < 253 ||
	    center[1] < 62 || center[1] > 66 || center[2] > 2 ||
	    center[3] < 253 || corner[3] < 253 ||
	    corner[0] > 2 || corner[1] < 30 || corner[1] > 34 ||
	    corner[2] < 126 || corner[2] > 130)
		return 1;
	glDeleteProgram(program);
	glDeleteShader(vs);
	glDeleteShader(fs);
	eglMakeCurrent(d, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
	eglDestroySurface(d, s);
	eglDestroyContext(d, c);
	eglTerminate(d);
	puts(allow_software ? "Software test harness passed" : "Adreno 418 shader/readback passed");
	return 0;
egl_error:
	fprintf(stderr, "EGL %s failed: %#x\n", phase, eglGetError());
	return 1;
}
