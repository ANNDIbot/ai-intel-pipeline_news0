#!/bin/bash

# --- 配置区 ---
VENV_NAME="venv"
ENTRY_POINT="src/main.py"
LOG_FILE="state/pipeline.log"

# 确保在脚本所在的目录执行
cd "$(dirname "$0")"
mkdir -p state

echo "------------------------------------------"
echo "🔍 正在检查本地环境..."

# 1. 自动处理虚拟环境
if [ ! -d "$VENV_NAME" ]; then
    echo "🔄 正在创建虚拟环境..."
    python3 -m venv "$VENV_NAME"
fi

# 2. 激活并同步依赖 (以 requirements.txt 为准)
source "$VENV_NAME/bin/activate"
echo "📦 正在同步依赖..."
python3 -m pip install --upgrade pip > /dev/null 2>&1
if [ -f "requirements.txt" ]; then
    python3 -m pip install -r requirements.txt > /dev/null 2>&1
else
    echo "❌ 错误: 未找到 requirements.txt"
    exit 1
fi

# 3. 配置运行环境
# ⚠️ 安全提醒: 不要在脚本中硬编码 API Key
# 建议在你的 ~/.zshrc 或 ~/.bash_profile 中 export
if [ -z "$DEEPSEEK_API_KEY" ]; then
    echo "⚠️ 警告: 未检测到环境变量 DEEPSEEK_API_KEY"
    # 这里可以保留你本地测试用的 export，但提交前务必删除
fi

# 解决本地运行时的模块导入路径问题
export PYTHONPATH=$PYTHONPATH:$(pwd)/src

# 4. 启动 Pipeline
echo "🚀 启动 AI Intel Pipeline (本地模式)..."
python3 "$ENTRY_POINT" 2>&1 | tee -a "$LOG_FILE"

echo "------------------------------------------"
echo "✅ 任务完成。日志查看: $LOG_FILE"