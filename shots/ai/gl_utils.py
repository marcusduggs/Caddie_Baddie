"""
Runtime helper to pre-load libGLESv2.so.2 and libEGL.so.1 stubs.

mediapipe's C shared library links against these at dlopen() time even when
running CPU-only inference on a headless server. By pre-loading a minimal
stub with RTLD_GLOBAL, their symbols become available to all subsequent
dlopen() calls in the same process — no system installation or root needed.

Call ensure_gl_stubs() once before creating any mediapipe landmarker.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import tempfile

_attempted = False

# ── OpenGL ES 2.0 symbols ─────────────────────────────────────────────────────
_GLES2 = [
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

# ── EGL 1.4 symbols ───────────────────────────────────────────────────────────
_EGL = [
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


def _compile_and_preload(soname: str, symbols: list[str]) -> bool:
    """Compile a stub shared library and load it into the global symbol table."""
    # Check if the library is already available on the system
    try:
        ctypes.CDLL(soname)
        return True
    except OSError:
        pass

    stub_path = f'/tmp/{soname}'
    c_src = f'// {soname} minimal stub\n' + '\n'.join(
        f'void {s}(void) {{}}' for s in symbols
    )

    cfile = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src)
            cfile = f.name

        result = subprocess.run(
            ['gcc', '-shared', '-fPIC', f'-Wl,-soname,{soname}', '-o', stub_path, cfile],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f'gl_utils: gcc failed for {soname}: {result.stderr[:300]}', flush=True)
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f'gl_utils: cannot compile {soname}: {exc}', flush=True)
        return False
    finally:
        if cfile and os.path.exists(cfile):
            try:
                os.unlink(cfile)
            except OSError:
                pass

    # Load with RTLD_GLOBAL so its symbols are visible to all future dlopen() calls
    try:
        ctypes.CDLL(stub_path, mode=ctypes.RTLD_GLOBAL)
        print(f'gl_utils: {soname} stub pre-loaded globally (CPU inference should work)', flush=True)
        return True
    except OSError as exc:
        print(f'gl_utils: failed to preload {soname} stub: {exc}', flush=True)
        return False


def ensure_gl_stubs() -> None:
    """Pre-load libGLESv2 and libEGL stubs if missing. Idempotent."""
    global _attempted
    if _attempted:
        return
    _attempted = True
    _compile_and_preload('libGLESv2.so.2', _GLES2)
    _compile_and_preload('libEGL.so.1', _EGL)
