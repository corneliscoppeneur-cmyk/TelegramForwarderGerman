from utils.i18n import t

VERSION = "1.7.2"

# 版本号说明
VERSION_INFO = {
    "major": 1,        # 主版本号：重大更新，可能不兼容旧版本
    "feature": 7,      # 功能版本号：添加重要新功能
    "minor": 2,        # 次要版本号：添加小功能或优化
    "patch": 0,        # 补丁版本号：Bug修复和小改动
} 


UPDATE_INFO = t("changelog.text")


WELCOME_TEXT = t("welcome.text", version=VERSION)