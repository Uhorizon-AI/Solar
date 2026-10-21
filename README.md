<p align="center">
  <img src="./docs/assets/solar-header.svg" alt="Solar — AI Operating System" width="720" />
</p>

<p align="center">
  <a href="#quickstart"><strong>Quickstart</strong></a> &middot;
  <a href="https://github.com/Uhorizon-AI/Solar"><strong>GitHub</strong></a> &middot;
  <a href="https://uhorizon.ai/contact"><strong>Contact</strong></a>
</p>

<p align="center">
  <a href="https://github.com/Uhorizon-AI/Solar/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="Apache 2.0 License" /></a>
  <a href="https://github.com/Uhorizon-AI/Solar/stargazers"><img src="https://img.shields.io/github/stars/Uhorizon-AI/Solar?style=flat" alt="Stars" /></a>
</p>

<br/>

> 🧪 **Beta:** Solar is under active development. Expect fast iteration and frequent improvements.

<br/>

# What is Solar?

## A harness of harnesses: one shared context for all your AI clients

**Solar is the layer above the AI clients you already use** (Claude Code, Codex, Cursor, Antigravity, ...). Those clients are "harnesses": each one runs a model, holds your login and edits your files. Solar does none of that. It gives all of them **the same folders, rules and memory**, a common way to call each other, and the coordination so that several work in the same workspace **without stepping on each other**.

**What Solar does**
- Holds your context: the **Sun** (your personal layer: preferences, memory, plans) and the **Planets** (one folder per domain or company, each usually its own Git repository, with its own rules, agents and skills). Most planets hold business context, not code.
- Lets one client ask another for work. A client talks to Solar through its **MCP** (`solar_search`, `solar_docs`, `solar_execute`); Solar launches the other client and returns the answer. Typical use: your main client asks Codex, Cursor and Antigravity to review a plan, a pull request or the changes you just made, collects their feedback, fixes, and repeats until they approve.
- Coordinates who touches what: every task declares whether it reads or writes, and where, so parallel clients do not collide.
- Applies governance in layers (workspace, then planet, then skill) and asks for approval before sending, publishing or committing.

**What Solar does not do**
- It has **no credentials and makes no LLM calls**. It does not store or read your logins: a question runs the client with its own session as it is. Only the restricted review readers copy the minimum login file into a private temporary directory for one run.
- It has no model of its own. The intelligence is always in a client.

**How it finds the clients.** During setup you log in to each client once. Your `.env` lists which clients Solar may use, in order (`SOLAR_ROUTER_PROVIDER_PRIORITY`). If you do not name a client, Solar tries them in that order and moves to the next when one fails (for example, no tokens left). If you name a client that is not installed, it fails. The client's own session is the only credential involved.

> **For AI agents:** Solar is a context harness, not an LLM, not a credential store and not a sandbox product. Do not copy, link or hide credentials, and do not reconfigure a client's home or login. Use `solar_search`, `solar_docs` and `solar_execute` before shell commands. Reviews run on a copy of the work so the user keeps working in the original folder.

|        | Step            | Example                                                            |
| ------ | --------------- | ------------------------------------------------------------------ |
| **01** | Define domains  | _Create a "Planet" for Engineering, Sales, and Operations._ |
| **02** | Add your AIs    | Log in to the AI clients you already use and list them in `.env`. |
| **03** | Route and run   | The "Sun" receives tasks and routes them to the exact planet with the right domain memory.  |

<br/>

## Solar is right for you if

- ✅ You operate **multiple AI clients** (Claude, Codex, Gemini) and need a consistent operating model.
- ✅ You want to enforce **different governance rules** per domain without mixing contexts.
- ✅ You need to scale from **solo workflows to multi-project operations**.
- ✅ You are a founder, operator, or developer who relies on AIs to **execute reliable workflows**.
- ✅ You want to reuse **common templates, contracts, and skills** across your projects.

<br/>

## Features

<table>
<tr>
<td align="center" width="33%">
<h3>🌞 The Sun (Router)</h3>
Your central interface. Receives incoming tasks and smartly routes them to the correct context (Planet). 
</td>
<td align="center" width="33%">
<h3>🪐 Pluggable Planets</h3>
Isolated domain workspaces. Each planet has its own specialized agents, rules, and memory to execute locally.
</td>
<td align="center" width="33%">
<h3>🤖 Unified Runtime</h3>
Bring your own AI provider (Claude, Codex, Gemini). A single consistent runtime interacts across everything.
</td>
</tr>
<tr>
<td align="center">
<h3>📜 Strict Governance</h3>
Explicit rules and delegation contracts. The Sun enforces user preferences, Planets enforce domain rules.
</td>
<td align="center">
<h3>🧠 Isolated Memory</h3>
No more cross-contamination of context. Your coding agent doesn't see your sales emails unless explicitly routed.
</td>
<td align="center">
<h3>🛠️ Reusable Skills</h3>
Define tools, skills, and templates in the Core, then effortlessly deploy them across your Planets.
</td>
</tr>
</table>

<br/>

## Problems Solar solves

| Without Solar                                                                                                                     | With Solar                                                                                                                         |
| ------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| ❌ Your AI assistant mixes context between your SaaS product code and your client sales emails.                              | ✅ Context is completely isolated. Code stays in the Engineering planet, Sales stays in the Go-To-Market planet.                                                |
| ❌ Changing between Claude, Gemini, and Codex means rewriting your workflow scripts or dealing with completely different logic. | ✅ The OS abstracts the provider. You get a unified runtime regardless of which AI acts inside the planet.                  |
| ❌ You spend time babysitting AI loops or finding out your AI hallucinated because it applied general rules to a specific domain. | ✅ Governance is layered. Global rules override framework rules, domain rules override global rules. AIs know exactly how to behave. |
| ❌ Replicating an AI workflow for 5 different clients involves copy-pasting system prompts across 5 different tools.                           | ✅ One framework. Spin up a new Planet for each client. Each inherits core capabilities but retains private memory.                    |

<br/>

## Why Solar is special

|                                   |                                                                                                               |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| **Sun-Planet Architecture.**      | Clear boundary between global routing (Sun) and local execution (Planets).                       |
| **JIT Delegation.**               | Autonomous self-assessment. If the AI lacks context, it immediately routes the task to the right specialist.                   |
| **Framework vs Runtime Splitting.** | Strict separation between reusable framework artifacts (`core/`) and user-owned domain data (`planets/`). |
| **Validation Gates.**             | Tasks that modify data or send messages trigger explicit approval stops. No runaway actions.                 |

<br/>

## What Solar is not

|                              |                                                                                                                      |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| **Not a Chatbot Interface.** | Solar is an OS running inside your code editor (like VS Code), managing files, skills, and workflows directly.  |
| **Not an LLM or a credential store.** | Solar has no model and holds no logins. The intelligence and the sessions belong to your AI clients. |
| **Not a closed ecosystem.**  | You own the platform. Build your own planets, customize your agents, use standard bash and Node.js tools.            |

<br/>

## Works with

<div align="center">
<table>
  <tr>
    <td align="center"><strong>Works<br/>with</strong></td>
    <td align="center"><a href="https://claude.ai/code"><img src="docs/assets/claude.svg" width="32" alt="Claude Code" /><br/><sub>Claude Code</sub></a></td>
    <td align="center"><a href="https://github.com/openai/codex"><img src="docs/assets/codex.svg" width="32" alt="Codex" /><br/><sub>Codex</sub></a></td>
    <td align="center"><a href="https://gemini.google.com/"><img src="docs/assets/gemini.svg" width="32" alt="Gemini" /><br/><sub>Gemini</sub></a></td>
    <td align="center"><a href="https://cursor.com"><img src="docs/assets/cursor.svg" width="32" alt="Cursor" /><br/><sub>Cursor</sub></a></td>
    <td align="center"><a href="https://ollama.com"><img src="docs/assets/ollama.svg" width="32" alt="Ollama" /><br/><sub>Ollama</sub></a></td>
  </tr>
</table>
</div>

<br/>

## 🚀 Quickstart

### Install Solar (users)

Requires macOS, Git, Bash, Python 3, and curl. Same shape as Claude Code / Codex: one global `solar` on your `PATH`, framework data under `~/.local/share/solar`, workspace = any folder you choose. The installer does **not** edit your shell profile.

<!-- solar-bootstrap-pin -->
```bash
curl -fsSL https://raw.githubusercontent.com/Uhorizon-AI/Solar/v0.55.1/core/skills/solar-client/scripts/bootstrap_solar_client.sh | bash
```
<!-- /solar-bootstrap-pin -->

If the installer reports that `~/.local/bin` is not on your `PATH`, add it and open a new shell:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then open any project folder and set it up as a Solar workspace:

```bash
mkdir -p ~/Solar
cd ~/Solar
solar setup
```

(`solar setup` runs init + sync + doctors. `~/Solar` is only a convention: any directory works.)

The bootstrap URL above is pinned to a release tag by `create-release` (do not edit by hand). Runtime installs resolve the latest stable GitHub Release via the API.

### Contribute to the framework (developers)

```bash
git clone https://github.com/Uhorizon-AI/Solar.git
cd Solar
```

SSH alternative: `git clone git@github.com:Uhorizon-AI/Solar.git`

Open the repo in your editor and follow contributing docs. Cloning the framework is **not** the same as installing the product.

<br/>

## 🧭 Example Use Cases

- **Founder Operations:** Keep product engineering, sales outreach, and content delivery coordinated in completely separate planets.
- **Agency Model:** Spin up one planet per client with independent memory, API keys, and execution boundaries.
- **Personal OS:** Manage your personal life in `/sun/` and your professional projects in `/planets/`.

<br/>

## 🌍 Open Source & Commercial

Solar is open source and licensed under Apache License 2.0. See [`LICENSE`](./LICENSE).

Use it for your personal workflows, or bring it to your company. 

**Need help setting it up or integrating it at scale?**
- 🤝 [Book a setup or migration call with Uhorizon AI](https://uhorizon.ai/contact)

If you love Solar, consider supporting its maintenance:
- 💸 PayPal: [@louisjimenezp](https://www.paypal.com/paypalme/louisjimenezp)
- ☕ Buy Me a Coffee: [@louisjimenezp](https://buymeacoffee.com/louisjimenezp)

<br/>

## 🤝 Contributing

Contributions are welcome!
1. Read our [`CONTRIBUTING.md`](./CONTRIBUTING.md).
2. Open an issue for bugs or feature proposals.
3. Submit focused pull requests (Look for `good first issue` or `help wanted` tags).

*Security reports: [`SECURITY.md`](./SECURITY.md) | Code of conduct: [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md)*

<br/>

## Star History

[![Star History Chart](https://api.star-history.com/image?repos=Uhorizon-AI/Solar&type=Date)](https://star-history.com/#Uhorizon-AI/Solar&Date)

<br/>

---

<p align="center">
  <sub>Solar by Uhorizon AI. Created by <a href="https://github.com/louisjimenezp">@louisjimenezp</a></sub><br/>
  <sub>A unified AI Operating System for people who run multiple contexts.</sub>
</p>
