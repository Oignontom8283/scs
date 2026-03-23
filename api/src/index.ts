import { PrismaClient } from "@prisma/client";
import prismaConfig from "../prisma.config"; // adapter le chemin

const prisma = new PrismaClient(prismaConfig);

const app = express();
const prisma = new PrismaClient();
const port = 3000;

app.use(express.json());

// Route GET all users
app.get("/users", async (req, res) => {
  const users = await prisma.user.findMany();
  res.json(users);
});

// Route POST new user
app.post("/users", async (req, res) => {
  const { name, email } = req.body;
  try {
    const user = await prisma.user.create({
      data: { name, email },
    });
    res.status(201).json(user);
  } catch (error) {
    res.status(400).json({ error: "Impossible de créer l'utilisateur." });
  }
});

// Start server
app.listen(port, () => {
  console.log(`Serveur démarré sur http://localhost:${port}`);
});