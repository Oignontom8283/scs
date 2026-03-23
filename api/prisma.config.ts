import { PrismaConfig } from "@prisma/client";

const config: PrismaConfig = {
  datasources: {
    db: {
      adapter: "sqlite",
      url: "file:./dev.db", // chemin vers ta DB SQLite
    },
  },
};

export default config;