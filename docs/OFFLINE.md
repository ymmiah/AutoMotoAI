# Offline AI: a model on this computer, with nothing else to install

Open **Settings → Offline AI** at any time. AutoMoto downloads a model and a small inference
engine (llama.cpp) into its own folder. You do not install Ollama, Python, or llama.cpp yourself.

The first download needs the internet. After the model and the engine are on the computer,
chat works with the network off. Prompts and files for that chat stay on the PC.

Phones can open the app, but they do not run these models. The model runs on the computer
where AutoMoto is installed.

## What you do

1. Open **Settings → Offline AI**.
2. Read the memory and disk line on each model. A row marked **Won't fit** explains why this
   computer cannot run it. Pick a row that fits, or the one marked **Best fit**.
3. Click **Download**. The first time this also fetches the engine. Leave the app open until
   the row says the file is ready.
4. Click **Use**, then **Test**. Test sends one short prompt to the model on this computer.
5. Optional: tick **Offline only**. Cloud models and web search stay off until you turn it off
   or click **Use cloud providers**.

You can **Delete** a downloaded model. **Import** copies a `.gguf` file you already have, or
you can upload one. AutoMoto checks that the file starts with the GGUF marker. It does not
promise that a custom file will fit in memory.

## Which model

Full **Kimi K2** is about a trillion parameters. Even the Q4 copy is about **624 GB** and is
split into many files. It is listed so that size is visible, and there is no download button
for it.

These are the sizes of the Q4 copies in the catalog. A graphics card is not required. The
built-in engine uses the CPU, so larger models answer more slowly.

| Model | Disk | Memory | Notes |
|---|---|---|---|
| Kimi-VL A3B Thinking | about 10 GB | 16 GB, 24 GB comfortable | Moonshot's smaller open model. Text only in this download. |
| Kimi K2 thinking distill, 32B | about 20 GB | 32 GB | A community distill, not the original trillion-parameter weights. |
| Qwen 2.5 0.5B / 1.5B / 3B / 7B | 0.4–4.7 GB | 2–16 GB | 3B is the everyday laptop pick. 7B is tight on 8 GB. |
| Llama 3.2 1B / 3B, Llama 3.1 8B | 0.8–4.9 GB | 4–16 GB | Llama community licence. |
| Mistral 7B Instruct v0.3 | about 4.4 GB | 8 GB, 16 GB comfortable | Apache-2.0. |
| Gemma 3 1B / 4B | 0.8–3.3 GB | 4–12 GB | Short chats. Tool steps use a slower text format. Gemma terms. |
| DeepSeek R1 distill 1.5B / 8B | 1.1–4.9 GB | 4–16 GB | Reasoning models. Slower answers. MIT. |
| Phi-3.5 mini / Phi-4 mini | about 2.5 GB | 6–8 GB | MIT. |

If this computer does not have enough memory, the row stays disabled and says how much it
needs. If the disk is too full, the download stays disabled and says how much free space is missing.

## Optional: Ollama

If Ollama is already installed, **Settings → Offline AI → Already using Ollama** can start it
and keep using an Ollama model. New setups do not need it.

A separate OpenAI-compatible server on this computer still works with `LOCAL_LLM_URL`
(for example `http://127.0.0.1:8080/v1`). AutoMoto will not call a server on the public internet.

## Something's not working

| What you see | What to do |
|---|---|
| Won't fit | Pick a smaller model. The text names the memory this computer has and the memory the model needs. |
| Download stays off | Free some disk space, or pick a smaller file. |
| The engine did not start | The model may be too large, or this CPU type has no published engine build. The page says which. |
| Test sits there | The first load is the slow one. A smaller model finishes sooner. |
| Offline only, and chat says nothing is set up | Download a model and press Use, or turn Offline only off. |
| A studio review still mentions Ollama | That older review path uses Ollama when you have not selected a built-in model. Select one under Offline AI and try the chat. |

More: [Start here](START.md) · [Help in the app](GUI-GUIDE.md) · [Store release steps](store/RELEASE_STEPS.md)
