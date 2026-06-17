#!/usr/bin/env python3
"""
Compile minimal libGLESv2.so.2 and libEGL.so.1 stubs for mediapipe.

mediapipe's C shared library links against these at load time even when
running CPU-only inference on a headless server. This script checks whether
each library is already loadable; if not, it compiles an empty stub (all
required symbols as no-op functions) and installs it to the standard
system library directory. Run once during the build phase as root.
"""
import ctypes
import os
import subprocess
import sys
import tempfile

LIB_DIR = '/usr/lib/x86_64-linux-gnu'

# Full OpenGL ES 2.0 symbol table
GLES2_SYMBOLS = [
    "glActiveTexture", "glAttachShader", "glBindAttribLocation", "glBindBuffer",
    "glBindFramebuffer", "glBindRenderbuffer", "glBindTexture", "glBlendColor",
    "glBlendEquation", "glBlendEquationSeparate", "glBlendFunc", "glBlendFuncSeparate",
    "glBufferData", "glBufferSubData", "glCheckFramebufferStatus", "glClear",
    "glClearColor", "glClearDepthf", "glClearStencil", "glColorMask", "glCompileShader",
    "glCompressedTexImage2D", "glCompressedTexSubImage2D", "glCopyTexImage2D",
    "glCopyTexSubImage2D", "glCreateProgram", "glCreateShader", "glCullFace",
    "glDeleteBuffers", "glDeleteFramebuffers", "glDeleteProgram", "glDeleteRenderbuffers",
    "glDeleteShader", "glDeleteTextures", "glDepthFunc", "glDepthMask", "glDepthRangef",
    "glDetachShader", "glDisable", "glDisableVertexAttribArray", "glDrawArrays",
    "glDrawElements", "glEnable", "glEnableVertexAttribArray", "glFinish", "glFlush",
    "glFramebufferRenderbuffer", "glFramebufferTexture2D", "glFrontFace", "glGenBuffers",
    "glGenerateMipmap", "glGenFramebuffers", "glGenRenderbuffers", "glGenTextures",
    "glGetActiveAttrib", "glGetActiveUniform", "glGetAttachedShaders",
    "glGetAttribLocation", "glGetBooleanv", "glGetBufferParameteriv", "glGetError",
    "glGetFloatv", "glGetFramebufferAttachmentParameteriv", "glGetIntegerv",
    "glGetProgramInfoLog", "glGetProgramiv", "glGetRenderbufferParameteriv",
    "glGetShaderInfoLog", "glGetShaderiv", "glGetShaderPrecisionFormat",
    "glGetShaderSource", "glGetString", "glGetStringi", "glGetTexParameterfv",
    "glGetTexParameteriv", "glGetUniformfv", "glGetUniformiv", "glGetUniformLocation",
    "glGetVertexAttribfv", "glGetVertexAttribiv", "glGetVertexAttribPointerv",
    "glHint", "glIsBuffer", "glIsEnabled", "glIsFramebuffer", "glIsProgram",
    "glIsRenderbuffer", "glIsShader", "glIsTexture", "glLineWidth", "glLinkProgram",
    "glPixelStorei", "glPolygonOffset", "glReadPixels", "glReleaseShaderCompiler",
    "glRenderbufferStorage", "glSampleCoverage", "glScissor", "glShaderBinary",
    "glShaderSource", "glStencilFunc", "glStencilFuncSeparate", "glStencilMask",
    "glStencilMaskSeparate", "glStencilOp", "glStencilOpSeparate", "glTexImage2D",
    "glTexParameterf", "glTexParameterfv", "glTexParameteri", "glTexParameteriv",
    "glTexSubImage2D", "glUniform1f", "glUniform1fv", "glUniform1i", "glUniform1iv",
    "glUniform2f", "glUniform2fv", "glUniform2i", "glUniform2iv", "glUniform3f",
    "glUniform3fv", "glUniform3i", "glUniform3iv", "glUniform4f", "glUniform4fv",
    "glUniform4i", "glUniform4iv", "glUniformMatrix2fv", "glUniformMatrix3fv",
    "glUniformMatrix4fv", "glUseProgram", "glValidateProgram", "glVertexAttrib1f",
    "glVertexAttrib1fv", "glVertexAttrib2f", "glVertexAttrib2fv", "glVertexAttrib3f",
    "glVertexAttrib3fv", "glVertexAttrib4f", "glVertexAttrib4fv",
    "glVertexAttribPointer", "glViewport",
]

# Full EGL 1.4 symbol table
EGL_SYMBOLS = [
    "eglBindAPI", "eglBindTexImage", "eglChooseConfig", "eglCopyBuffers",
    "eglCreateContext", "eglCreatePbufferFromClientBuffer", "eglCreatePbufferSurface",
    "eglCreatePixmapSurface", "eglCreateWindowSurface", "eglDestroyContext",
    "eglDestroySurface", "eglGetConfigAttrib", "eglGetConfigs",
    "eglGetCurrentContext", "eglGetCurrentDisplay", "eglGetCurrentSurface",
    "eglGetDisplay", "eglGetError", "eglGetProcAddress", "eglInitialize",
    "eglMakeCurrent", "eglQueryAPI", "eglQueryContext", "eglQueryString",
    "eglQuerySurface", "eglReleaseTexImage", "eglReleaseThread",
    "eglSurfaceAttrib", "eglSwapBuffers", "eglSwapInterval", "eglTerminate",
    "eglWaitClient", "eglWaitGL", "eglWaitNative",
]


def _can_load(soname: str) -> bool:
    try:
        ctypes.CDLL(soname)
        return True
    except OSError:
        return False


def make_stub(soname: str, symbols: list) -> bool:
    if _can_load(soname):
        print(f'{soname}: already loadable — skipping stub')
        return True

    out = os.path.join(LIB_DIR, soname)
    c_src = f'// {soname} minimal stub for mediapipe on headless servers\n'
    for sym in symbols:
        c_src += f'void {sym}(void) {{}}\n'

    cfile = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src)
            cfile = f.name

        result = subprocess.run(
            ['gcc', '-shared', '-fPIC', f'-Wl,-soname,{soname}', '-o', out, cfile],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f'{soname}: stub compiled → {out}')
            return True
        else:
            print(f'{soname}: gcc FAILED:\n{result.stderr[:500]}', file=sys.stderr)
            return False
    except FileNotFoundError:
        print('gcc not found — cannot compile stub', file=sys.stderr)
        return False
    finally:
        if cfile and os.path.exists(cfile):
            os.unlink(cfile)


if __name__ == '__main__':
    try:
        os.makedirs(LIB_DIR, exist_ok=True)
    except PermissionError:
        print(f'No write access to {LIB_DIR} — skipping stub creation', file=sys.stderr)
        sys.exit(0)

    created = False
    created |= make_stub('libGLESv2.so.2', GLES2_SYMBOLS)
    created |= make_stub('libEGL.so.1', EGL_SYMBOLS)

    if created:
        r = subprocess.run(['ldconfig'], capture_output=True, text=True)
        if r.returncode == 0:
            print('ldconfig: cache updated')
        else:
            print(f'ldconfig warning: {r.stderr[:200]}')

    # Final verification
    for soname in ('libGLESv2.so.2', 'libEGL.so.1'):
        status = 'OK' if _can_load(soname) else 'STILL MISSING'
        print(f'  {soname}: {status}')
