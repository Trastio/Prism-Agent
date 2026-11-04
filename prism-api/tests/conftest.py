# -*- coding: utf-8 -*-
"""
登录门禁 change（2026-10-15）：既有离线单测的门禁旁路。

既有用例（dashboard/month/as_of/export）离线直调 TestClient，无登录流程——门禁全开
会全部 401。auth_gate 中间件留了进程内旁路开关 `app.state.auth_bypass`（非 env、
非配置文件，仅同进程可设——生产部署无路径触达），conftest 在 import main 后置 True，
test_auth.py 内按需关闭验证真门禁。
"""
import os
import sys
from pathlib import Path

# 固定密钥：测试间 token 签验一致（须在 import main 之前设置）
os.environ.setdefault('PRISM_AUTH_SECRET', 'pytest-secret')

sys.path.insert(0, str(Path(__file__).parent.parent))
import main as prism_main  # noqa: E402

prism_main.app.state.auth_bypass = True
