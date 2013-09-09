====================
Partial PyPI Mirrors
====================

Sometimes you want a PyPI mirror, but you don't want the whole thing. You
certainly don't want external links. What you want are the things that you
need and nothing more. What's more, you often know exactly what you need
because you already have a pip requirements.txt file containing the list of
things you expect to download from PyPI.

pypi-mirror will build a local static mirror for you based on requirements
files in git repos.
