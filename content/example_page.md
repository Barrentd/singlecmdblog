---
title: About This Blog
subtitle: Learn more about SingleCmdBlog
page: true
---

This is an example page that demonstrates how to create static pages in SingleCmdBlog. Unlike blog posts, pages are typically used for permanent content that doesn't change frequently.

## What Makes This a Page?

Notice the `page: true` in the YAML front matter above. This tells SingleCmdBlog to treat this as a static page rather than a blog post, which means:

- It won't appear in the blog post listings
- It won't be included in category pages
- It's perfect for "About", "Contact", or other permanent content

## Page Features

### All the Same Markdown Support

- **Bold text** and *italic text*
- Lists (like this one!)
- Code blocks
- Links and images

### Code Example

```python
# Pages support code highlighting too
def hello_world():
    print("Hello from a static page!")
```

## Perfect For

- About pages
- Contact information
- Privacy policies
- Terms of service
- Portfolio pages
- Any permanent content

## Simple Setup

Creating a page is as easy as:
1. Create a `.md` file in the `content/` directory
2. Add `page: true` to the YAML front matter
3. Write your content in Markdown
4. Run `python3 build.py`
