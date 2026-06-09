# 实时通话代理（语音/视频通话的 WS + 视觉/风控 HTTP）。
# node_modules 被 .gitignore 忽略，所以在镜像内安装依赖，不依赖主机挂载。
FROM node:20-alpine
WORKDIR /app

# 先装依赖（利用缓存层）
COPY package.json package-lock.json* ./
RUN npm install --omit=dev

# 再拷源码
COPY . .

EXPOSE 8870
CMD ["node", "doubao-realtime-proxy.mjs"]
