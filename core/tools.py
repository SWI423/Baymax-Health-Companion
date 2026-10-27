"""
大白工具说明书（Agent 化 · 路线A：原生 function calling）

模型通过 tools 参数"看到"这些工具，自主决定是否调用、调哪个：
  - save_memory      用户要求记住某事时 → 写入三层记忆（替代正则解析 [MEMORY]）
  - set_reminder     用户设定/取消定时提醒时 → 写提醒表（替代正则解析 [REMINDER]）
  - search_knowledge 用户描述健康症状时 → 检索医疗知识库（替代每次无条件注入）

本文件只定义工具的 JSON Schema（纯数据，不 import 任何业务模块），
执行函数在 brain.py 的 TOOL_REGISTRY 中绑定 —— 避免循环依赖。
"""
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "用户明确要求你记住某件事时调用（例如“帮我记住…”“别忘了…”“记住…”“记下来…”）。把要记住的内容用用户原话整理后传入，不要添加你自己的评价或建议。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要记住的内容，整理自用户原话，例如“用户明天下午三点要交作业”"
                    },
                    "source": {
                        "type": "string",
                        "enum": ["user_require", "user_auto"],
                        "description": "user_require=用户明确要求记住（原话带“记住/别忘了”等）；user_auto=用户只是自然提到但值得记住"
                    }
                },
                "required": ["content", "source"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "用户设定或取消定时提醒/闹钟时调用（例如“明天早上九点提醒我吃药”“每天下午3点提醒我做眼保健操”“取消吃药提醒”）。time 填具体时刻；date 填相对词或具体日期（今天/明天/后天/下周一/YYYY-MM-DD），缺省表示每天重复。",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {
                        "type": "string",
                        "description": "提醒内容，如 吃药、做眼保健操"
                    },
                    "time": {
                        "type": "string",
                        "description": "提醒时刻，如 09:00、下午三点、晚上十点"
                    },
                    "date": {
                        "type": "string",
                        "description": "日期：今天/明天/后天/下周X/YYYY-MM-DD；缺省=每天重复"
                    },
                    "action": {
                        "type": "string",
                        "enum": ["set", "cancel"],
                        "description": "set=设定（默认）；cancel=取消该事件名的提醒"
                    }
                },
                "required": ["event_name", "time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "用户描述身体不适、健康问题、疾病护理等需要专业健康知识时调用（例如“我最近总是头晕”“眼睛干”“发烧了”）。用用户的核心症状词作为 question 检索医疗知识库。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "检索关键词，如 头晕、眼睛干涩、低血糖、发烧护理"
                    }
                },
                "required": ["question"]
            }
        }
    },
]
