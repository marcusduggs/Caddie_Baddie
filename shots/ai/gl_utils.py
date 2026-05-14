"""
Runtime helper to pre-load libGLESv2.so.2 and libEGL.so.1 stubs.

mediapipe's C shared library (libmediapipe.so) links against OpenGL ES at
dlopen() time even for CPU-only inference.  By pre-loading a stub that
provides every GL/EGL symbol the library references, we satisfy the dynamic
linker without needing a GPU or a real OpenGL installation.

Strategy:
  1. Use `nm` on the actual libmediapipe.so to get the precise list of
     undefined GL/EGL symbols (exact, no guesswork).
  2. Fall back to a comprehensive predefined GLES2+3.0+3.1 + EGL list if
     nm is unavailable.
  3. Compile a minimal stub (all symbols as empty C functions) via gcc.
  4. Load the stub with ctypes.RTLD_GLOBAL so its symbols are visible to
     all subsequent dlopen() calls in the same process.

Call ensure_gl_stubs() once before creating any mediapipe landmarker.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import tempfile

_attempted = False

# ── OpenGL ES 2.0 ─────────────────────────────────────────────────────────────
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

# ── OpenGL ES 3.0 additions ───────────────────────────────────────────────────
_GLES30 = [
    "glBeginQuery", "glBeginTransformFeedback", "glBindBufferBase", "glBindBufferRange",
    "glBindSampler", "glBindTransformFeedback", "glBindVertexArray", "glBlitFramebuffer",
    "glClearBufferfi", "glClearBufferfv", "glClearBufferiv", "glClearBufferuiv",
    "glClientWaitSync", "glCompressedTexImage3D", "glCompressedTexSubImage3D",
    "glCopyBufferSubData", "glCopyTexSubImage3D", "glDeleteQueries", "glDeleteSamplers",
    "glDeleteSync", "glDeleteTransformFeedbacks", "glDeleteVertexArrays",
    "glDrawArraysInstanced", "glDrawBuffers", "glDrawElementsInstanced",
    "glDrawRangeElements", "glEndQuery", "glEndTransformFeedback", "glFenceSync",
    "glFlushMappedBufferRange", "glFramebufferTextureLayer", "glGenQueries",
    "glGenSamplers", "glGenTransformFeedbacks", "glGenVertexArrays",
    "glGetActiveUniformBlockiv", "glGetActiveUniformBlockName", "glGetActiveUniformsiv",
    "glGetBufferParameteri64v", "glGetBufferPointerv", "glGetFragDataLocation",
    "glGetInteger64i_v", "glGetInteger64v", "glGetIntegeri_v", "glGetInternalformativ",
    "glGetProgramBinary", "glGetQueryiv", "glGetQueryObjectuiv",
    "glGetSamplerParameterfv", "glGetSamplerParameteriv", "glGetSynciv",
    "glGetTransformFeedbackVarying", "glGetUniformBlockIndex", "glGetUniformIndices",
    "glGetUniformuiv", "glGetVertexAttribIiv", "glGetVertexAttribIuiv",
    "glInvalidateFramebuffer", "glInvalidateSubFramebuffer", "glIsQuery", "glIsSampler",
    "glIsSync", "glIsTransformFeedback", "glIsVertexArray", "glMapBufferRange",
    "glPauseTransformFeedback", "glProgramBinary", "glProgramParameteri", "glReadBuffer",
    "glRenderbufferStorageMultisample", "glResumeTransformFeedback",
    "glSamplerParameterf", "glSamplerParameterfv", "glSamplerParameteri",
    "glSamplerParameteriv", "glTexImage3D", "glTexStorage2D", "glTexStorage3D",
    "glTexSubImage3D", "glTransformFeedbackVaryings",
    "glUniform1ui", "glUniform1uiv", "glUniform2ui", "glUniform2uiv",
    "glUniform3ui", "glUniform3uiv", "glUniform4ui", "glUniform4uiv",
    "glUniformBlockBinding",
    "glUniformMatrix2x3fv", "glUniformMatrix2x4fv", "glUniformMatrix3x2fv",
    "glUniformMatrix3x4fv", "glUniformMatrix4x2fv", "glUniformMatrix4x3fv",
    "glUnmapBuffer", "glVertexAttribDivisor",
    "glVertexAttribI4i", "glVertexAttribI4iv", "glVertexAttribI4ui", "glVertexAttribI4uiv",
    "glVertexAttribIPointer", "glWaitSync",
]

# ── OpenGL ES 3.1 additions (compute shaders, image load/store) ───────────────
_GLES31 = [
    "glActiveShaderProgram", "glBindImageTexture", "glBindProgramPipeline",
    "glBindVertexBuffer", "glCreateShaderProgramv", "glDeleteProgramPipelines",
    "glDispatchCompute", "glDispatchComputeIndirect", "glDrawArraysIndirect",
    "glDrawElementsIndirect", "glFramebufferParameteri", "glGenProgramPipelines",
    "glGetBooleani_v", "glGetFramebufferParameteriv", "glGetMultisamplefv",
    "glGetProgramInterfaceiv", "glGetProgramPipelineInfoLog", "glGetProgramPipelineiv",
    "glGetProgramResourceIndex", "glGetProgramResourceiv",
    "glGetProgramResourceLocation", "glGetProgramResourceName",
    "glGetTexLevelParameterfv", "glGetTexLevelParameteriv", "glIsProgramPipeline",
    "glMemoryBarrier", "glMemoryBarrierByRegion",
    "glProgramUniform1f", "glProgramUniform1fv", "glProgramUniform1i",
    "glProgramUniform1iv", "glProgramUniform1ui", "glProgramUniform1uiv",
    "glProgramUniform2f", "glProgramUniform2fv", "glProgramUniform2i",
    "glProgramUniform2iv", "glProgramUniform2ui", "glProgramUniform2uiv",
    "glProgramUniform3f", "glProgramUniform3fv", "glProgramUniform3i",
    "glProgramUniform3iv", "glProgramUniform3ui", "glProgramUniform3uiv",
    "glProgramUniform4f", "glProgramUniform4fv", "glProgramUniform4i",
    "glProgramUniform4iv", "glProgramUniform4ui", "glProgramUniform4uiv",
    "glProgramUniformMatrix2fv", "glProgramUniformMatrix2x3fv", "glProgramUniformMatrix2x4fv",
    "glProgramUniformMatrix3fv", "glProgramUniformMatrix3x2fv", "glProgramUniformMatrix3x4fv",
    "glProgramUniformMatrix4fv", "glProgramUniformMatrix4x2fv", "glProgramUniformMatrix4x3fv",
    "glSampleMaski", "glTexStorage2DMultisample", "glUseProgramStages",
    "glValidateProgramPipeline", "glVertexAttribBinding", "glVertexAttribFormat",
    "glVertexAttribIFormat", "glVertexBindingDivisor",
]

# ── EGL 1.4 + extensions ──────────────────────────────────────────────────────
_EGL = [
    "eglBindAPI", "eglBindTexImage", "eglChooseConfig", "eglCopyBuffers",
    "eglCreateContext", "eglCreateImage", "eglCreatePbufferFromClientBuffer",
    "eglCreatePbufferSurface", "eglCreatePixmapSurface",
    "eglCreatePlatformPixmapSurface", "eglCreatePlatformWindowSurface",
    "eglCreateSync", "eglCreateWindowSurface", "eglDestroyContext",
    "eglDestroyImage", "eglDestroySurface", "eglDestroySync",
    "eglGetConfigAttrib", "eglGetConfigs", "eglGetCurrentContext",
    "eglGetCurrentDisplay", "eglGetCurrentSurface", "eglGetDisplay",
    "eglGetError", "eglGetPlatformDisplay", "eglGetProcAddress",
    "eglGetSyncAttrib", "eglInitialize", "eglMakeCurrent", "eglQueryAPI",
    "eglQueryContext", "eglQueryString", "eglQuerySurface", "eglReleaseTexImage",
    "eglReleaseThread", "eglSurfaceAttrib", "eglSwapBuffers", "eglSwapInterval",
    "eglTerminate", "eglWaitClient", "eglWaitGL", "eglWaitNative", "eglWaitSync",
]


def _get_mediapipe_lib_path() -> str | None:
    """Return the path to mediapipe's bundled C shared library, if present."""
    try:
        import mediapipe
        lib = os.path.join(os.path.dirname(mediapipe.__file__), 'tasks', 'c', 'libmediapipe.so')
        return lib if os.path.exists(lib) else None
    except Exception:
        return None


def _get_required_symbols(lib_path: str | None) -> list[str]:
    """Return GL/EGL symbols needed by libmediapipe.so.

    Uses `nm` for precision; falls back to the full predefined list.
    """
    if lib_path:
        try:
            r = subprocess.run(
                ['nm', '-D', '--undefined-only', lib_path],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0:
                syms = []
                for line in r.stdout.splitlines():
                    parts = line.strip().split()
                    if parts:
                        s = parts[-1]
                        if s.startswith('gl') or s.startswith('egl'):
                            syms.append(s)
                if syms:
                    print(f'gl_utils: nm extracted {len(syms)} GL/EGL symbols from libmediapipe.so', flush=True)
                    return syms
        except Exception:
            pass
    # Comprehensive fallback: GLES 2.0 + 3.0 + 3.1 + EGL
    return _GLES2 + _GLES30 + _GLES31 + _EGL


def _compile_and_preload(soname: str, symbols: list[str]) -> bool:
    """Compile a stub shared library and load it into the global symbol table."""
    try:
        ctypes.CDLL(soname)
        print(f'gl_utils: {soname} already available on system', flush=True)
        return True
    except OSError:
        pass

    stub_path = f'/tmp/{soname}'
    c_src = f'// {soname} stub — empty implementations\n' + '\n'.join(
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

    try:
        ctypes.CDLL(stub_path, mode=ctypes.RTLD_GLOBAL)
        print(f'gl_utils: {soname} stub pre-loaded globally', flush=True)
        return True
    except OSError as exc:
        print(f'gl_utils: failed to preload {soname} stub: {exc}', flush=True)
        return False


def ensure_gl_stubs() -> None:
    """Pre-load libGLESv2 and libEGL stubs with all required symbols. Idempotent."""
    global _attempted
    if _attempted:
        return
    _attempted = True

    lib_path = _get_mediapipe_lib_path()
    symbols = _get_required_symbols(lib_path)

    # Split into gl* and egl* groups so each has the right SONAME
    gl_syms = [s for s in symbols if s.startswith('gl')]
    egl_syms = [s for s in symbols if s.startswith('egl')]

    if gl_syms:
        _compile_and_preload('libGLESv2.so.2', gl_syms)
    if egl_syms:
        _compile_and_preload('libEGL.so.1', egl_syms)
