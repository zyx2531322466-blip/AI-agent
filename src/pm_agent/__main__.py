"""支持 ``python -m pm_agent``，方便没装命令行的环境下直接跑。"""

from .cli import app

if __name__ == "__main__":
    app()
