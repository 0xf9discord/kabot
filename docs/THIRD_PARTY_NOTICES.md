# Third-party notices

The read-only chat pagination/title fields and TLS service-identity observations
also reference [agent-messenger](https://github.com/agent-messenger/agent-messenger),
commits `e58739d80305d5e8ddf72e9aad085c2069f4fd3c` and
`f4990c8d6172d0b8c4e1523262ee94349c120ff7`. The Python algorithms were written
independently with bounded cursors and explicit identity checks. For attribution:

MIT License

Copyright (c) 2026 Jeon Suyeol

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

## Initial LOCO implementation references

The experimental LOCO framing, field identifiers, reference RSA public key and
cryptographic handshake format, desktop-profile session requests and message
envelopes in `src/kabot/loco/`
were implemented with reference to the MIT-licensed project below. The Python
implementation adds strict method validation, configurable bounded parsing,
incremental decoding and authenticated-record checks.

- Project: [openkakao-cli](https://github.com/JungHoonGhae/openkakao-cli)
- Pinned source commit: `6ca6ea2fd05a6660c4a80c0b61b43b416653d1d5`
- Sources: `src/loco/packet.rs`, `src/loco/crypto.rs`, `src/loco/client.rs`,
  `src/loco/message.rs`, `src/commands/send.rs`
- Reference format and public key are historical source observations; they
  do not establish current live server compatibility or successful login.

## openkakao-cli license

MIT License

Copyright (c) 2026 Lucas (JungHoonGhae)

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

## node-kakao open-chat profile protocol reference

Open-chat profile serialization and switching use schemas described by
[node-kakao](https://github.com/storycraft/node-kakao), pinned commit
`8512e4699e2cd4c26516b80d38b57b2f85a6cc8a`. Relevant sources are
`open-link-profile.ts`, `talk-open-channel-session.ts`, and
`talk-open-link-session.ts`. Reference source scripts were not executed.

MIT License

Copyright (c) 2021 storycraft

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

## loco-wrapper protocol reference

The independent Android authentication request builders and Android LOCO profile
use protocol facts described in
[loco-wrapper](https://github.com/NetRiceCake/loco-wrapper), pinned commit
`1dec3b79e59f2776ebd1f03e60744162ff195b24` (2026-10-03), particularly
`KakaoApi.java` and outbound login request models. The following notice is
included for reference and attribution. Source scripts were not executed.

MIT License

Copyright (c) 2026 NetRiceCake

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
