# -*- coding: utf-8 -*-
"""磁化率测定 —— pcal 包。"""
from .version import APP_VERSION as __version__

from . import magnetic
from . import analysis
from . import plotting

__all__ = ['magnetic', 'analysis', 'plotting']
