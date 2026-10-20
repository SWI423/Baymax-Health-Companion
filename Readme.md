# 🤖 Baymax Health Companion (大白私人陪伴者)

> 一个基于大语言模型、具有长期记忆、情绪感知与 RAG 检索能力的桌面级心理与健康陪伴机器人。
> *“你好，我是大白，你的私人健康顾问。”*

<!-- 建议截图替换这里 -->
<!-- ![Demo](demo.png) -->

## 🌟 项目简介
本项目旨在通过大语言模型（LLM）与物理交互（表情、语音）的结合，打造一个长期陪伴的桌面机器人。区别于传统的“问答机器人”，大白拥有**长期记忆机制**，能记住用户的偏好与病史；具备**情绪感知能力**，能根据用户的输入即时改变面部表情；内置**本地医疗 RAG**，提供专业、安全的健康建议。

## 🧠 核心架构与亮点

1. **双轨制大模型调度引擎 (Two-Pass Architecture)**
   - 基于 **LangChain (LCEL)** 构建。Pass 1 专注于“流式聊天输出”；Pass 2 独立进行后台 JSON 提取（意图、情绪、动作），主线程零阻塞。
2. **混合语义记忆系统 (Hybrid RAG)**
   - 结合 SQLite 与智谱 Embedding API（2048维），通过 Numpy 计算余弦相似度。支持“短期对话原话”+“长期记忆向量”混合检索。
3. **高精准记忆防污染机制 (Anti-Pollution)**
   - 代码级拦截 + Prompt 铁律，防止大模型将自身的“反问/建议”当作“用户事实”存入记忆库。
4. **7 状态有限状态机 (FSM)**
   - 涵盖休眠、问候、待机、聊天、关心、提醒、催促。由事件驱动，结合 Pygame 实现平滑的动画反馈。
5. **反导师腔与拨云见日 (Persona)**
   - 彻底去除 AI 爹味，拒绝废话和列表式说教，专注于提供情绪价值。

## 🛠️ 技术栈
- **语言**：Python 3.10
- **框架**：LangChain (LCEL)
- **大模型**：智谱 GLM-4 (对话) / Embedding-3 (向量化)
- **本地存储**：SQLite3 (关系数据 + 向量 JSON 存储)
- **前端渲染**：Pygame
- **工具库**：NumPy, Threading, Queue

## 🚀 快速启动

1. 克隆项目并安装依赖：
   ```bash
   git clone https://github.com/SWI423/Baymax-Health-Companion.git
   cd Baymax-Health-Companion
   pip install -r requirements.txt
   
2. 配置 API Key：
复制 config.example.py 为 config.py，填入你的智谱 API Key。

3. 初始化医疗知识库：

```bash
python tools/init_rag_db.py --clear
```
4. 启动大白：

```bash
python main.py
```
操作提示：按 W 唤醒，按 Space 终端输入文字对话。

## 以下是当前项目进度有关材料和测试示范:

### 1.状态图
<img width="865" height="621" alt="image" src="https://github.com/user-attachments/assets/ab674053-35ad-4797-956e-7a955fc7751b" />

### 2.测试示范
<img width="865" height="307" alt="image" src="https://github.com/user-attachments/assets/93c35f15-3d51-4729-8194-7880cd1bf00e" />
<img width="865" height="277" alt="image" src="https://github.com/user-attachments/assets/79882401-b7f3-4526-af2f-2dbcdefad8b2" />
<img width="865" height="601" alt="image" src="https://github.com/user-attachments/assets/c8539dd3-9f10-43bf-853f-6533d235742d" />
<img width="865" height="466" alt="image" src="https://github.com/user-attachments/assets/2960ffb2-fe8a-446b-916e-dde07db73874" />





