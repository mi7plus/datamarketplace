FROM node:20-slim

WORKDIR /app

# Copy package.json first for caching
COPY package*.json ./

# Use npm install (not ci)
RUN npm install

# Copy rest of the files
COPY . .

EXPOSE 3000

CMD ["npx", "nuxt", "dev", "--hostname", "0.0.0.0", "--port", "3000"]