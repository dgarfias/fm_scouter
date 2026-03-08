from setuptools import setup, Extension

try:
    from Cython.Build import cythonize
    extensions = cythonize(
        [Extension("fm_scout._parser", ["fm_scout/_parser.pyx"])],
        compiler_directives={"language_level": "3"},
    )
except ImportError:
    extensions = []

setup(
    name="fm_scout",
    ext_modules=extensions,
)
