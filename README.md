# SingleCmdBlog

> Write it, build it, ship it

## What is this?

SingleCmdBlog is a ridiculously simple static blog generator that fits in a single Python file. No databases, no PHP nightmares, no "oops I broke my site by updating a plugin" moments.

**Features:**

- Write in Markdown (like a civilized human)
- Dark/Light theme toggle
- Categories
- Mobile-friendly (your mom can read it on her phone)
- Fast as lightning (14KB page limit enforced!)
- Zero dependencies (well, Python... but that's it!)

## Quick Start

**The "I want it NOW" way:**

### 1. Write some content in content/my-first-post.md

```markdown
---
title: My First Post
date: 2024-01-01
categories: blog, thoughts
---

This is easier than assembling IKEA furniture.
```

### 2. Build the site

```bash
python3 build.py
```

### 3. Serve it locally (because we live dangerously)

```bash
python3 build.py --serve
```

Open http://localhost:8080 and boom 💥 You have a blog.

## Docker Way (for the cool kids)

```bash
# Build the image
docker build -f Dockerfile.test -t singlecmdblog .

# Run it (your blog will live at http://localhost:8080)
docker run -p 8080:80 singlecmdblog

# Feel superior to WordPress users
```

## File Structure

```bash
tinyblog/
├── build.py          # The magic happens here ✨
├── content/          # Your brilliant thoughts go here
│   ├── hello.md      # Example post
│   └── about.md      # Tell the world who you are
├── public/           # Static files (images, etc.)
└── build/            # Generated site (don't touch, it bites)
```

## Writing Posts

Create a `.md` file in `content/`. Start with some front matter (fancy name for metadata):

```markdown
---
title: Why Cats Rule the Internet
date: 2024-01-15
categories: cats, philosophy, internet
---

# Your brilliant content here

Cats are basically tiny furry overlords...
```

**Pro tips:**

- Date format: `YYYY-MM-DD`
- Categories: comma-separated (spaces optional, life is short)
- Pages: add `page: true` to front matter for non-blog pages

## Customization

- **Site config:** Edit the variables at the top of `build.py`
- **Theme:** CSS is embedded (because external files are overrated)
- **Colors:** Dark theme uses CSS variables (look for `:root`)

## Deployment

**Static hosting (recommended):**

- Netlify: drag & drop the `build/` folder
- GitHub Pages: push `build/` contents
- Any web server: upload `build/` contents

**Or use the Docker image** (because containers solve everything):

```bash
docker run -p 80:80 tinyblog
```

## Size Limits (because nobody likes slow sites)

- **Index page:** 14KB max (warning if exceeded)
- **Article pages:** 30KB max (warning if exceeded)
- **Other pages:** 14KB max (warning if exceeded)

*If you hit these limits, maybe consider splitting your novel into chapters* 😉

---

## License

MIT License - because sharing is caring! 🎉

```text
Copyright (c) 2025 TinyBlog Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Made with ❤️ and an unhealthy obsession with simplicity.

## SingleCmdBlog v1.0 - When 900 lines of Python beat 50MB of WordPress
