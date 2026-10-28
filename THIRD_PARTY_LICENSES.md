# Third-party components and licenses

This project ships the following third-party file unchanged. It is the only
vendored component; all Python code uses the standard library.

## three.js

- File: `web/vendor/three.min.js`
- Version: r140 (see the `@license` header in the file)
- License: MIT
- Copyright: Copyright © 2010-2022 Three.js Authors
- Source: https://github.com/mrdoob/three.js

```text
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

## Board photo

- Files: `web/assets/m2-board-top.png`, `web/assets/m2-board-bottom.png`
- Source: photographs of the Quectel Pi M2 board supplied for this demo
- Use: top and bottom face textures in the 3D view; cropped/alpha-matted from the supplied images

## Python dependencies

`requirements.txt` intentionally contains no packages. The HTTP server, I2C
transport and attitude filter use only the Python standard library.
