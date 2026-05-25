FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .

# API base injected at build time so rewrites are correct inside Docker
ARG NEXT_PUBLIC_API_BASE=http://ui-api:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE

RUN npm run build

FROM node:20-alpine

WORKDIR /app
COPY package*.json ./
RUN npm ci --production
COPY --from=builder /app/.next ./.next
RUN mkdir -p ./public

EXPOSE 3000
CMD ["npm", "start"]
