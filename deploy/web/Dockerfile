# 웹 화면: 프론트를 빌드해 nginx 로 서빙하고 /api 는 api 컨테이너로 넘긴다.
# 빌드 컨텍스트는 저장소 루트(deploy/docker-compose.yml 의 web.build)다.
FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY deploy/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
