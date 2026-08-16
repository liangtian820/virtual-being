# Virtual Being 鈥?AI 铏氭嫙浜虹墿

涓€涓?*鑳芥矡閫氱殑涓撳睘 Agent**锛氭俯鏌旀不鎰堢殑浜屾鍏冭鑹诧紝閫氳繃杩炴帴澶氫釜 Agent 鏋勫缓锛屾棦鑳介櫔浼磋亰澶┿€佷篃鑳藉綋鍔╂墜骞叉椿銆?
> **GitHub 浠撳簱**锛歚https://github.com/liangtian820/virtual-being`
> 褰撳墠涓烘湰鍦?git 浠撳簱锛岀瓑寰呴娆℃帹閫侊紙README 寰界珷鍦ㄦ帹閫佸悗琛ュ厖锛夈€?
## 褰撳墠鐘舵€侊細M6锛堟墦纾ㄤ笌灞曠ず锛?
- 鉁?M1 鏂囨湰鐏甸瓊锛歄llama 鏈湴鎺ㄧ悊锛坬wen2.5:7b锛? 浜烘牸 Agent + 浼氳瘽鍐呰蹇?- 鉁?M2 鑳藉姏鎵╁睍锛氱煡璇嗘煡璇?+ 璁＄畻鑳藉姏 Agent锛堟剰鍥捐矾鐢便€佷汉璁惧寘瑁咃級锛汳2.1 杩藉姞瑙勫垝鍔╂墜 + 鏃ョ▼澶囧繕锛圵O-20260816-20锛夛紱M2.2 鏃ョ▼/瑙勫垝澧炲己锛氬懆鍑犺В鏋愩€佸垹闄?瀹屾垚鏍囪銆侀噸澶嶆彁閱掋€佽鍒掔粨鏋滀繚瀛橈紙WO-20260816-23锛?- 鉁?M3 涓撳睘璁板繂锛歋QLite 璺ㄤ細璇濋暱鏈熻蹇嗭紙fact + topic锛?- 鉁?M3.5 璁板繂鍚戦噺鍖栵細Ollama all-minilm 璇箟妫€绱?+ jieba 涓枃鍒嗚瘝 + 璇箟/鍏抽敭璇嶈瀺鍚堬紙`app/memory/`锛?- 鉁?M4 璇煶锛欰SR锛圵hisper 鏈湴璇嗗埆锛屼腑鏂囷級+ TTS锛坋dge-tts 涓枃濂冲０锛? 璇煶瀵硅瘽閾捐矾锛堣鈫掑惉鈫掑洖鈫掓挱锛?- 鉁?M4.3/M4.4 璇煶 <5s 鍐插埡 + 鍗辨満瀹夊叏琛ヤ竵锛氶粯璁?`llama3.2:3b + piper 鏈湴 TTS`锛屽嵄鏈鸿矾寰勪唬鐮佸眰寮哄埗涓撲笟姹傚姪寮曞
- 鉁?M5 褰㈣薄锛歐eb 鑱婂ぉ鐣岄潰锛堢▼搴忓寲鍘熷垱绔嬬粯 + 琛ㄦ儏鐘舵€?+ 璇煶鎺т欢锛?- 鉁?M5.1 鎰忓浘璺敱 + 璁板繂闂瓟锛圵O-20260816-22锛夛細浜烘牸瀵硅瘽婵€娲昏鍒?鏃ョ▼鑳藉姏 Agent锛坄is_planning_query`/`is_schedule_query`锛夈€?  璁板繂闂瓟璧板悜閲忔绱紙`retrieve_fused`锛夈€佽蹇?API锛坄GET/DELETE /memory`锛夈€佷腑鏂囧彛璇澶硅嫳鏂?- 鉁?M5.2 Web 鑳藉姏闈㈡澘锛圵O-20260816-24锛夛細鏃ョ▼闈㈡澘锛堜粖鏃?鏄庢棩鍒楄〃 + 鏂板/瀹屾垚/鍒犻櫎锛夈€佽鍒掗潰鏉匡紙宸蹭繚瀛樿鍒掑垪琛?鍒犻櫎 +
  瀵硅瘽鍐呮楠ゅ崱鐗囷級銆佽蹇嗛潰鏉匡紙鏌ョ湅/娓呯┖甯︾‘璁わ級锛涙柊 API `GET/POST /schedule`銆乣POST /schedule/{id}/done`銆?  `DELETE /schedule/{id}`銆乣GET/POST /plans`銆乣DELETE /plans/{id}`
- 馃毀 M6 鎵撶（灞曠ず锛歊EADME 鏋舵瀯鍥句笌婕旂ず鑴氭湰锛堣繘琛屼腑锛夈€佽鑹蹭竴鑷存€ц瘎娴嬶紙`docs/consistency_testset.md`锛夈€丟itHub 浠撳簱鍑嗗

## 鍔熻兘娓呭崟

| 鑳藉姏 | 閲岀▼纰?| 璇存槑 | 鍏ュ彛 |
| --- | --- | --- | --- |
| 鏂囨湰瀵硅瘽锛堜汉鏍硷級 | M1 | 娓╂煍娌绘剤浜屾鍏冧汉璁撅紝Ollama qwen2.5:7b 鏈湴鎺ㄧ悊 | `POST /chat`銆乣scripts/run_demo.py` |
| 鑳藉姏鎵╁睍 | M2 | 鐭ヨ瘑鏌ヨ + 璁＄畻 + 瑙勫垝 + 鏃ョ▼澶囧繕鑳藉姏 Agent锛堟剰鍥捐矾鐢便€佷汉璁惧寘瑁咃級 | `app/agents/knowledge_agent.py`銆乣calculator_agent.py`銆乣planning_agent.py`銆乣schedule_agent.py` |
| 瑙勫垝鍔╂墜 | M2.1 | 妯＄硦鐩爣 鈫?缁撴瀯鍖栨楠ゆ竻鍗曪紙鐩爣/甯﹀簭鍙锋楠?棰勪及浼樺厛绾э紝LLM 鐢熸垚銆佽緭鍑?JSON锛?| `app/agents/planning_agent.py`銆乣app/tools/planning.py` |
| 鏃ョ▼澶囧繕 | M2.1 | 鑷劧璇█鎻愰啋 鈫?鏃ョ▼鏉＄洰锛堟椂闂?浜嬮」锛? SQLite 鎸佷箙鍖栵紙`data/`锛実itignored锛? 浠婃棩/鏄庢棩鏌ヨ | `app/agents/schedule_agent.py`銆乣app/tools/schedule.py` |
| 鏃ョ▼澧炲己 | M2.2 | 鍛ㄥ嚑瑙ｆ瀽锛堛€庡懆涓変笅鍗堝悆鑽€忊啋 鏈€杩戜竴涓懆涓夛紝datetime 璺ㄥ懆杈圭晫锛? 鍒犻櫎锛堛€庡垹鎺夋槑澶╀笅鍗堢殑鎻愰啋銆忥級+ 瀹屾垚鏍囪锛堛€庝粖澶╁枬姘寸殑鎻愰啋瀹屾垚浜嗐€忥級+ 閲嶅鎻愰啋锛堛€庢瘡澶╂棭涓婃彁閱掓垜鍠濇按銆忥級 | `app/agents/schedule_agent.py`銆乣app/tools/schedule.py` |
| 瑙勫垝淇濆瓨 | M2.2 | 瑙勫垝缁撴灉鍙繚瀛橈紙銆庢妸杩欎釜璁″垝瀛樹笅鏉ャ€忊啋 SQLite `data/plans.db`锛? 璁″垝鍒楄〃/鍒犻櫎 | `app/agents/planning_agent.py`銆乣app/tools/planning.py` |
| 涓撳睘璁板繂 | M3/M3.5 | SQLite 璺ㄤ細璇濋暱鏈熻蹇嗭紙fact/topic 鎶藉彇銆佸幓閲嶃€佺嚎绋嬪畨鍏級+ 鍚戦噺璇箟妫€绱笌鍏抽敭璇嶈瀺鍚?| `app/memory/long_term_memory.py`銆乣app/memory/embeddings.py` |
| 璇煶瀵硅瘽 | M4 | 璇粹啋鍚啋鍥炩啋鎾細Whisper ASR锛堟湰鍦拌瘑鍒級+ edge-tts TTS锛堜腑鏂囧コ澹帮級 | `POST /chat/voice`銆乣scripts/run_voice_demo.py` |
| 褰㈣薄锛圵eb 鐣岄潰锛?| M5 | 绋嬪簭鍖栧師鍒涚珛缁?+ 4 琛ㄦ儏鐘舵€?+ 鎸変綇璇磋瘽璇煶鎺т欢 | `GET /`銆乣web/` |
| 鑳藉姏闈㈡澘锛圵eb锛?| M5.2 | 鏃ョ▼闈㈡澘锛堜粖鏃?鏄庢棩 + 澧炲垹瀹屾垚锛夈€佽鍒掗潰鏉匡紙鍒楄〃/鍒犻櫎 + 瀵硅瘽鍐呮楠ゅ崱鐗囷級銆佽蹇嗛潰鏉匡紙鏌ョ湅/娓呯┖甯︾‘璁わ級 | `web/`銆乣/schedule`銆乣/plans`銆乣/memory` |
| 寤惰繜浼樺寲 | M4.1/M4.2 | Ollama keep_alive銆佸洖澶嶆埅鏂€乀TS LRU 缂撳瓨銆丄SR 鍚姩棰勫姞杞?| 璇佹嵁 `data/m4_voice/evidence_m4{1,2}.json` |

## 蹇€熷紑濮?
```powershell
pip install -r requirements.txt
python -m scripts.run_demo                # CLI 鏂囨湰瀵硅瘽
python -m scripts.run_voice_demo --self-test   # CLI 璇煶瀵硅瘽锛堣嚜鍔ㄧ敓鎴愪腑鏂囪緭鍏?鈫?鍏ㄩ摼璺級
uvicorn app.main:app --port 8000         # Web 鏈嶅姟
```

瑕佹眰锛氭湰鏈哄凡瀹夎骞跺惎鍔?[Ollama](https://ollama.com)锛屽凡鎷夊彇 `qwen2.5:7b`銆?
### Web 鑱婂ぉ鐣岄潰锛圡5锛?
鍚姩鏈嶅姟鍚庯紝娴忚鍣ㄦ墦寮€ **http://127.0.0.1:8000/** 鍗冲彲涓?TA 闈㈠闈㈣亰澶╋細

- **绔嬬粯褰㈣薄**锛氱▼搴忓寲鍘熷垱 SVG 浜屾鍏冪珛缁橈紙娓╂煍娌绘剤椋庯紝鏃犵増鏉冮闄╋級锛屽甫杞诲井娴姩/鍛煎惛鍔ㄦ€?- **琛ㄦ儏鐘舵€?*锛氶粯璁?/ 鎬濊€?/ 璇磋瘽 / 寮€蹇冿紝闅忓璇濊嚜鍔ㄥ垏鎹紙鍙戦€佹椂鎬濊€冦€佸洖澶嶆椂璇磋瘽銆佹敹鍒板悗寮€蹇冿級
- **鏂囨湰瀵硅瘽**锛氳蛋鐪熷疄 `POST /chat` API锛堜笉閫犲亣鏁版嵁锛?- **璇煶瀵硅瘽**锛氭寜浣?馃帣 璇磋瘽 鈫?娴忚鍣ㄥ綍闊筹紙MediaRecorder锛夆啋 `POST /chat/voice` 鈫?鑷姩鎾斁鍥炲闊抽
- **鑳藉姏闈㈡澘锛圡5.2锛?*锛氬彸渚т笁闈㈡澘鈥斺€旔煋?鏃ョ▼锛堜粖鏃?鏄庢棩鍒楄〃锛屾柊澧炴彁閱掕緭鍏ワ紝鉁撳畬鎴?/ 鉁曞垹闄ゆ寜閽級銆?  馃棐 瑙勫垝锛堝凡淇濆瓨璁″垝鍒楄〃涓庡垹闄わ紱瀵硅瘽涓銆庡府鎴戣鍒掆€︺€忔椂鍥炲涓嬫柟鑷姩灞曠ず姝ラ鍗＄墖锛屾暟鎹潵鑷?`POST /plans` 鐪熷疄缁撴瀯鍖栫粨鏋滐級銆?  馃 璁板繂锛堟煡鐪?TA 璁颁綇鐨勫唴瀹癸紝娓呯┖闇€浜屾纭锛岃蛋 `DELETE /memory?confirm=1`锛?- 椤甸潰杞婚噺锛氬師鐢?HTML/CSS/JS 鍗曢〉锛屾棤妗嗘灦渚濊禆锛屾敮鎸佸噺寮卞姩鐢伙紙`prefers-reduced-motion`锛?
### 璇煶璇存槑锛圡4锛屽惈 M4.2 榛樿璋冧紭锛?
- **ASR**锛歠aster-whisper 鏈湴璇嗗埆锛岄粯璁?`base` 妯″瀷 + CPU(int8)锛坄ASR_MODEL_SIZE`/`ASR_DEVICE`/`ASR_COMPUTE_TYPE`锛夛紝
  閾句笂绋冲畾绾?0.9s 涓斾笉鍗犵敤 Ollama 鏄惧瓨銆?- **ASR 妯″瀷鏈湴璺緞**锛氶粯璁や粠椤圭洰 `data/models` 鍔犺浇锛坄ASR_MODEL_DIR` 鍙寚瀹氾紱鏀寔 HF 缂撳瓨甯冨眬
  `models--Systran--faster-whisper-{size}` 鎴栨墎骞崇洰褰曪級銆?*棣栨浣跨敤鏃犳湰鍦版ā鍨嬫椂**闇€鑱旂綉涓嬭浇涓€娆★細
  缃戠粶鐩磋繛涓嶇ǔ鏃惰缃?`HF_ENDPOINT=https://hf-mirror.com` 璧板浗鍐呴暅鍍忋€?- **TTS**锛歟dge-tts 鐜版垚闊宠壊锛堝井杞湪绾挎湇鍔★紝鍏嶈垂锛夛紝榛樿涓枃濂冲０銆屾檽鏅撱€峘zh-CN-XiaoxiaoNeural`锛涘悎鎴愰渶鑱旂綉锛?  鍚屾枃鏈懡涓?LRU 缂撳瓨锛坄TTS_CACHE_DIR`锛岄粯璁?`data/tts_cache`锛夋椂浠呯害 8ms銆?- **鐜鍙橀噺**锛歚ASR_MODEL_SIZE`锛坆ase/small/medium锛夈€乣ASR_DEVICE`锛坅uto/cuda/cpu锛夈€乣ASR_LANGUAGE`锛坺h/auto锛夈€?  `ASR_PRELOAD`锛?/0锛岄粯璁ゅ惎鍔ㄩ鍔犺浇锛夈€乣OLLAMA_KEEP_ALIVE`锛堥粯璁?`60m` 闀块┗锛夈€乣VOICE_MAX_REPLY_CHARS`锛堥粯璁?`60`锛夈€?  `TTS_VOICE`銆乣TTS_RATE`銆乣VOICE_REPLY_DIR` 绛夛紝瑙?`app/config.py`銆?- **闅愮**锛氫笉淇濆瓨鐢ㄦ埛璇煶鍘熷鏁版嵁锛圓PI 涓婁紶闊抽澶勭悊瀹屽嵆鍒狅級锛涗笉浣跨敤浠讳綍鏈巿鏉冮煶鑹诧紙绂佹澹伴煶鍏嬮殕锛夈€?
### 闀挎湡璁板繂锛圡3 / M3.5锛?
- **瀛樺偍**锛歋QLite 鍙岃〃鈥斺€擿memories`锛坒act/topic 鏂囨湰锛屾棦鏈夌粨鏋勪笉鍙橈級+ `memory_embeddings`锛堝悜閲忥紝
  鐙珛鏂拌〃锛屾棫鏁版嵁鎸夐渶 lazy 琛ュ悜閲忥紝涓嶈縼绉讳笉鐮村潖锛夈€?- **妫€绱笁鎺ュ彛**锛坄app/memory/long_term_memory.py`锛夛細
  - `retrieve(query, limit, days)` 鈥?鍏抽敭璇嶆绱紙鏃㈡湁琛屼负涓嶅彉锛屽悜鍚庡吋瀹癸級
  - `retrieve_semantic(query, k, days)` 鈥?鍚戦噺璇箟妫€绱紙Ollama all-minilm 浣欏鸡鐩镐技搴︼紝杩戜箟鍙懡涓級
  - `retrieve_fused(query, limit, days)` 鈥?璇箟 + 鍏抽敭璇嶅姞鏉冭瀺鍚堬紙榛樿 0.6/0.4锛屽彲閰嶇疆锛?- **涓枃鍒嗚瘝**锛歫ieba锛坄app/memory/embeddings.py#segment`锛夌敤浜?query/鏂囨湰棰勫鐞嗐€?- **embedding**锛歄llama 鏈湴 `all-minilm:latest`锛圚TTP `http://127.0.0.1:11434`锛屽甫瓒呮椂锛涙湇鍔′笉鍙敤鏃?  璇箟/铻嶅悎鑷姩闄嶇骇涓哄叧閿瘝妫€绱紝璁板繂璇诲啓涓嶅彈褰卞搷锛夈€?- **鐜鍙橀噺**锛歚EMBEDDING_MODEL`锛堥粯璁?`all-minilm:latest`锛夈€乣EMBEDDING_BASE_URL`銆?  `EMBEDDING_DIM`锛堥粯璁?384锛夈€乣MEMORY_SEMANTIC_THRESHOLD`锛堥粯璁?0.35锛夈€?  `MEMORY_FUSION_SEMANTIC_WEIGHT`/`MEMORY_FUSION_KEYWORD_WEIGHT`锛堥粯璁?0.6/0.4锛夈€?  `MEMORY_AUTO_BACKFILL`锛堥粯璁?1锛岃涔夋绱㈡椂瀵规棫鏁版嵁 lazy 琛ュ悜閲忥級锛岃 `app/config.py`銆?
### 鎰忓浘璺敱涓庤蹇嗛棶绛旓紙M5.1锛學O-20260816-22锛?
浜烘牸 Agent 鍦ㄥ璇濅腑鎸夐『搴忚矾鐢辨剰鍥撅紙鍗辨満 鈫?鐭ヨ瘑 鈫?璁＄畻 鈫?璁板繂闂瓟 鈫?瑙勫垝 鈫?鏃ョ▼ 鈫?鏅€氾級锛?鍛戒腑鑳藉姏鍒嗘敮鏃惰皟鐢ㄥ搴旇兘鍔?Agent 鍙?*缁撴瀯鍖栫粨鏋滄敞鍏ヤ笂涓嬫枃**锛屼汉璁惧寲鍥炲浠嶇敱浜烘牸 Agent 瀹屾垚
锛堣兘鍔?Agent 涓嶆姠浜鸿锛涜鍒ゅ畞鍙氦浜烘牸鑷敱鍙戞尌锛屼笉纭矾鐢憋級銆?
- **瑙勫垝**锛氥€庡府鎴戣鍒掑懆鏈鍋氶キ銆忊啋 `PlanningAgent.plan` 鈫?娉ㄥ叆姝ラ娓呭崟锛堢洰鏍?搴忓彿/浼樺厛绾э級鈫?浜鸿鍖栧彊杩?- **鏃ョ▼娣诲姞**锛氥€庢彁閱掓垜鏄庡ぉ涓嬪崍 3 鐐瑰枬姘淬€忊啋 `ScheduleAgent.add` 鈫?浜鸿鍖栫‘璁ゅ苟**鍥炴樉鏃ユ湡/鏃堕棿/浜嬮」**
- **鏃ョ▼鏌ヨ**锛氥€庢垜浠婂ぉ鏈変粈涔堝畨鎺掋€忊啋 `ScheduleAgent.today` 鈫?浠婃棩鏃ョ▼浜鸿鍖栧垪鍑?- **璁板繂闂瓟**锛氥€庝綘璁板緱鎴戝枩娆粈涔堝悧銆忋€庢垜涓婃璇寸殑璁″垝銆忊啋 `LongTermMemory.retrieve_fused`
  锛圡3.5 璇箟+鍏抽敭璇嶈瀺鍚堬級鏇挎崲鍘熷叧閿瘝娉ㄥ叆锛涖€庢垜鐨勮蹇嗘湁鍝簺銆忊啋 鎽樿绾у垪绀?- **涓枃鍙ｈ**锛氱郴缁熸彁绀鸿瘝杩藉姞銆愯瑷€銆戣鍒欌€斺€斿叏绋嬬畝浣撲腑鏂囧彛璇€佺姝㈠す鑻辨枃锛堝繀瑕佹湳璇櫎澶栵級銆?  鏁板瓧鏃堕棿鐢ㄤ腑鏂囦範鎯〃杈?- 鎰忓浘妫€娴嬪疄鐜帮細`app/agents/persona_agent.py`锛坄is_planning_query` / `is_schedule_query` /
  `is_schedule_lookup` / `is_memory_query` / `is_memory_list_query`锛屽己鍏抽敭璇嶄繚瀹堝尮閰嶏級

## API

- `GET /` 鈥?Web 鑱婂ぉ鐣岄潰棣栭〉锛堢珛缁?+ 瀵硅瘽绐?+ 璇煶鎺т欢锛?- `GET /static/*` 鈥?鍓嶇闈欐€佽祫婧愶紙css/js锛屾潵鑷?`web/` 鐩綍锛?- `POST /chat` 鈥?`{"query": "浣犲ソ", "session_id": "鍙€?}` 鈫?`{"reply": "...", "session_id": "..."}`
- `POST /chat/voice` 鈥?multipart 涓婁紶闊抽锛堝瓧娈?`file`锛屽彲閫?`session_id`锛夆啋
  `{"text", "reply", "session_id", "audio_url", "latencies_ms"}`锛沗audio_url` 鎸囧悜
  `GET /voice/replies/{filename}` 鍙洿鎺ユ挱鏀?- `GET /voice/replies/{filename}` 鈥?涓嬭浇/鎾斁鍥炲闊抽锛圡P3锛?- `GET /memory` 鈥?鍒楃ず闀挎湡璁板繂锛堟憳瑕佺骇锛宍?limit=N` 榛樿 50锛屾渶澶?200锛?- `DELETE /memory` 鈥?娓呯┖闀挎湡璁板繂锛堥渶 `?confirm=1` 纭锛岃繑鍥炲垹闄ゆ潯鏁板苟鐣欑棔鏃ュ織锛?- `GET /schedule?date=today|tomorrow` 鈥?鏌ヨ浠婃棩/鏄庢棩鏃ョ▼锛圡5.2锛?- `POST /schedule` 鈥?鑷劧璇█鎻愰啋璇?`{"text": "鏄庡ぉ涓嬪崍3鐐规彁閱掓垜鍠濇按"}` 鈫?201 + 缁撴瀯鍖栨潯鐩紙M5.2锛?- `POST /schedule/{id}/done` 鈥?鎸?id 鏍囪鏃ョ▼瀹屾垚锛圡5.2锛?- `DELETE /schedule/{id}` 鈥?鎸?id 鍒犻櫎鏃ョ▼锛圡5.2锛?- `GET /plans` 鈥?宸蹭繚瀛樿鍒掑垪琛紙鐩爣/姝ユ暟/鏃堕棿鎽樿锛孧5.2锛?- `POST /plans` 鈥?鐢熸垚瑙勫垝锛堜笉钀藉簱锛塦{"goal": "甯垜瑙勫垝鍛ㄦ湯瀛﹀仛楗?}` 鈫?201 + 缁撴瀯鍖栨楠ゆ竻鍗曪紙M5.2锛屽墠绔楠ゅ崱鐗囨暟鎹簮锛?- `DELETE /plans/{id}` 鈥?鍒犻櫎涓€浠藉凡淇濆瓨瑙勫垝锛圡5.2锛?- `GET /health` 鈥?鍋ュ悍妫€鏌?
```powershell
# 璇煶瀵硅瘽绀轰緥锛坈url锛?curl -F "file=@user.mp3" http://127.0.0.1:8000/chat/voice
```

## 鏋舵瀯

### 鍏ㄩ摼璺€昏锛圡1-M5锛?
```
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ 鐢ㄦ埛灞?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? Web 鑱婂ぉ鐣岄潰锛圡5锛?                      CLI 婕旂ず                   鈹?鈹? 绔嬬粯 + 4 琛ㄦ儏鐘舵€佹満    鎸変綇璇磋瘽(褰曢煶)     scripts/run_demo.py       鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                鈹?POST /chat (JSON 鏂囨湰)        鈹?POST /chat/voice (闊抽)
                鈻?                              鈻?鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ 鏈嶅姟灞傦紙FastAPI, app/main.py锛夆攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? /chat         浼氳瘽璁板繂(M1) + 闀挎湡璁板繂妫€绱?M3) 鈫?浜烘牸瀵硅瘽                       鈹?鈹? /chat/voice   ASR(M4) 鈫?浜烘牸瀵硅瘽 鈫?鍥炲鎴柇(M4.1) 鈫?TTS(M4)                   鈹?鈹? /voice/replies/{filename} 鍥炲闊抽涓嬭浇锛堥槻璺緞绌胯秺锛?                          鈹?鈹? /static銆?     Web 闈欐€佽祫婧愪笌鑱婂ぉ椤碉紙M5锛?                                    鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈻测攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                鈹?娉ㄥ叆宸ュ叿缁撴灉 / 璁板繂            鈹?鍥炲闊抽
                鈻?                              鈹?鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ Agent 灞?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? 浜烘牸 Agent锛堣鑹插崱 + 鎻愮ず璇嶏紝娓╂煍娌绘剤浜鸿锛?                                   鈹?鈹?   鈹溾攢 鎰忓浘璺敱 鈫?鐭ヨ瘑鏌ヨ/璁＄畻/瑙勫垝/鏃ョ▼鑳藉姏 Agent锛圡2/M5.1锛?                  鈹?鈹?   鈹溾攢 璁板繂闂瓟 鈫?闀挎湡璁板繂鍚戦噺铻嶅悎妫€绱紙M3.5/M5.1锛?                              鈹?鈹?   鈹斺攢 闀挎湡璁板繂锛歠act/topic 鎶藉彇銆佸幓閲嶃€丼QLite 鎸佷箙鍖栵紙M3锛?                     鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                               鈻?              Ollama qwen2.5:7b锛堟湰鍦?LLM锛宬eep_alive 闀块┗锛?```

鍒嗛摼璺粏鑺傝涓嬨€?
### 鏂囨湰閾捐矾锛圡1-M3锛?
```
鐢ㄦ埛杈撳叆 鈫?浼氳瘽璁板繂(鏈€杩慛杞? + 闀挎湡璁板繂妫€绱?鈫?浜烘牸Agent(瑙掕壊鍗?鎻愮ず璇?
         鈫?鎰忓浘璺敱(鐭ヨ瘑/璁＄畻鑳藉姏Agent娉ㄥ叆缁撴灉) 鈫?Ollama qwen2.5:7b 鈫?鍥炲
```

### 璇煶閾捐矾锛圡4锛?
```
鐢ㄦ埛璇煶闊抽 鈫?ASR(Whisper 鏈湴璇嗗埆) 鈫?浜烘牸Agent 瀵硅瘽 鈫?TTS(edge-tts 涓枃濂冲０) 鈫?鍥炲闊抽
   锛堣锛?           锛堝惉锛?                   锛堝洖锛?                     锛堣/鎾級
```

### 褰㈣薄閾捐矾锛圡5锛?
```
娴忚鍣?绔嬬粯+琛ㄦ儏鐘舵€佹満) 鈫?POST /chat(鏂囨湰) / POST /chat/voice(MediaRecorder 褰曢煶)
      鈫?鍚庣鐪熷疄閾捐矾 鈫?鍥炲鏂囨湰閫愬瓧"璇磋瘽"+鍥炲闊抽鑷姩鎾斁 鈫?琛ㄦ儏:鎬濊€冣啋璇磋瘽鈫掑紑蹇?```

## 寤惰繜鍩虹嚎锛圡4 瀹炴祴锛屾湰鏈猴細RTX 3060 Laptop 6GB + Ollama qwen2.5:7b GPU 82% offload锛?
鐪熷疄閾捐矾楠岃瘉锛坄data/m4_voice/evidence.json`锛夛細杈撳叆 4.03s 涓枃璇煶 鈫?璇嗗埆 鈫?Ollama 瀵硅瘽 鈫?鍥炲闊抽 12.1s銆?
| 鍒嗘 | 閾捐矾 1锛堝喎鍚姩/闀垮洖澶嶏級 | 閾捐矾 2锛圤llama 鐑?涓瓑鍥炲锛?| 璇存槑 |
| --- | --- | --- | --- |
| ASR锛圵hisper small锛?| 3.3s | 5.2s | 涓?LLM 浜夋姠 6GB 鏄惧瓨鏃舵尝鍔?|
| LLM锛坬wen2.5:7b锛?| 17.3s | 4.0s | 鍗曟鐭洖澶嶇害 1.3s锛涢暱鍥炲 + 鍐峰惎鍔ㄦ槑鏄惧彉鎱?|
| TTS锛坋dge-tts 鍦ㄧ嚎锛?| 1.5s | 1.8s | 12s 闊抽 |
| **绔埌绔?* | **22.1s** | **11.1s** | 鍔熻兘鍙敤锛岃窛"娴佺晠"锛?5s锛夋湭杈炬爣 |

**缁撹锛堝瀹炰笂鎶ワ級**锛歁4 閾捐矾鍔熻兘瀹屾暣銆佸彲杩愯锛屼絾绔埌绔欢杩熸湭杈?娴佺晠瀵硅瘽"鏍囧噯锛岄渶鎸変笅闈㈤檷绾ф柟妗堜紭鍖栧悗鎵嶇畻浣撻獙杈炬爣銆?
**闄嶇骇鏂规锛堟寜浼樺厛绾э級**锛?1. **鏄惧瓨浜夋姠**锛欰SR 涓?LLM 鍏辩敤 6GB 鏄惧瓨鏄?LLM 鍙樻參涓诲洜 鈫?ASR 鍥哄畾 `ASR_DEVICE=cpu`锛堝凡鍐呯疆鑷姩鍥為€€锛夋垨鎹?base/tiny锛汷llama `OLLAMA_CONTEXT_LENGTH` 璋冨皬銆?2. **鍥炲闀垮害绾︽潫**锛氫汉璁炬彁绀鸿瘝鍔?鍥炲 鈮?30 瀛椼€佸彛璇煭鍙?锛岀洿鎺ョ爫鎺?TTS 鏃堕暱涓?LLM 鐢熸垚鏃堕棿锛堟湰娆″洖澶?12s 闊抽鍋忛暱锛夈€?3. **LLM 鎹㈠皬妯″瀷**锛歚OLLAMA_MODEL=qwen2.5:3b` 鎴?`llama3.2:3b`锛堟湰鏈哄凡鎷夊彇锛夛紝鐢熸垚鎻愰€熸暟鍊嶃€?4. **ASR 鎹㈠皬妯″瀷**锛歚ASR_MODEL_SIZE=base`锛堢害 1-2s锛夋垨 tiny銆?5. **TTS 缂撳瓨**锛氱浉鍚屽洖澶嶆枃鏈鐢ㄥ悎鎴愮粨鏋滐紱甯哥敤寮€鍦虹櫧棰勫悎鎴愶紱鍥炲鍓嶅厛鎴柇銆?6. **甯搁┗杩涚▼**锛欰PI 妯″紡鍗曚緥闀块┗锛堟ā鍨嬪彧鍔犺浇涓€娆★級锛岄伩鍏嶆瘡娆¤姹傚喎鍚姩銆?
**GPU 鍔犻€熻鏄?*锛氭湰鏈烘棤 CUDA Toolkit锛學hisper 璧?GPU 闇€ `pip install nvidia-cublas-cu12` 骞舵妸
`<venv>\Lib\site-packages\nvidia\cublas\bin` 鍔犲叆 PATH锛涙湭閰嶇疆鏃?ASR 鑷姩鍥為€€ CPU int8锛堝瀹為檷绾э紝涓嶅亣瑁?GPU 鍙敤锛夈€?
## M4.1 寤惰繜浼樺寲锛堝疄娴嬪姣旓紝璇佹嵁 `data/m4_voice/evidence_m41.json`锛?
| 鍒嗘 | 浼樺寲鍓嶏紙M4 鍩虹嚎锛?| 浼樺寲鍚庯紙M4.1锛?| 鍙樺寲 |
| --- | --- | --- | --- |
| LLM 鍐峰惎鍔紙棣栬皟锛?| 17.3s | 3.4s | keep_alive 闀块┗鐢熸晥锛?80%锛?|
| LLM锛堢儹鎬佸璇濓級 | 4.5s | 4.1s | 绋冲畾 <5s |
| TTS锛堟湭鍛戒腑缂撳瓨锛?| 1.7s | 1.5~2.5s | 鈥?|
| TTS锛堢紦瀛樺懡涓級 | 鈥?| **7.7ms** | 璺宠繃鍦ㄧ嚎鍚堟垚 |
| 绔埌绔紙鐑€侊級 | 9.7s | 8.3s | 涓嬮檷 14%锛堝彈 ASR 娉㈠姩褰卞搷锛?|
| 闀垮洖澶嶅満鏅?| 22.1s锛?25 瀛楀叏鏂囧悎鎴愶級 | 43 瀛楁埅鏂悗鍚堟垚 | 璇煶鏃堕暱澶у箙缂╃煭 |

M4.1 涓夐」浼樺寲锛?
1. **Ollama keep_alive 闀块┗**锛坄OLLAMA_KEEP_ALIVE`锛岄粯璁?`60m`锛夛細妯″瀷甯搁┗鏄惧瓨/鍐呭瓨锛?   鍐峰惎鍔?17.3s 鈫?3.4s锛岀儹鎬佸璇濈ǔ瀹?<5s锛坄ollama ps` 鍙 UNTIL 59min锛夈€?2. **璇煶鍥炲闀垮害绾︽潫**锛坄VOICE_MAX_REPLY_CHARS`锛岄粯璁?`60`锛夛細pipeline 鍦?TTS 鍓嶆埅鏂埌鍙ユ湯鏍囩偣锛?   鐪熷疄閾捐矾 425 瀛楅暱鍥炲 鈫?43 瀛楄闊筹紙瀹屾暣鍥炲淇濈暀鍦?`reply_full`锛屼細璇濊蹇嗕笌鏂囨湰 API 涓嶅彈褰卞搷锛夈€?3. **TTS LRU 缂撳瓨**锛坄TTS_CACHE_DIR`/`TTS_CACHE_SIZE`锛岄粯璁?`data/tts_cache`/128锛夛細
   key = 鏂囨湰+闊宠壊+璇€燂紙sha1锛夛紝鍛戒腑鐩存帴澶嶇敤闊抽锛堝疄娴?7.7ms vs 鏈懡涓?1.4s锛夈€?
**ASR 鏉冭　瀹炴祴**锛堝悓杈撳叆 4.03s 涓枃锛? 娆′腑浣嶆暟锛屽噯纭巼鍧?1.0锛岃瘉鎹?`data/m4_voice/asr_bench.json`锛夛細

| 閰嶇疆 | 寤惰繜 | 寤鸿 |
| --- | --- | --- |
| base/CPU锛坕nt8锛?| 937ms | **M4.2 褰撳墠榛樿**锛氱ǔ瀹氫笖涓嶆姠 Ollama 鐨?6GB 鏄惧瓨 |
| base/GPU锛坕nt8_float16锛?| 228ms | 鏄惧瓨鍏呰/寤惰繜鏁忔劅棣栭€?|
| small/GPU锛坕nt8_float16锛?| 324ms | 闇€ cuBLAS + PATH锛堜細涓?LLM 浜夋樉瀛橈級 |
| small/CPU锛坕nt8锛?| 2523ms | 闇€瑕佹洿澶фā鍨嬬簿搴︽椂鍙€?|

**閬楃暀椋庨櫓**锛氶摼璺笂 ASR 瀹炴祴 2.6~9.3s 娉㈠姩锛堥娆?GPU 鎺ㄧ悊鍒濆鍖?+ 涓?Ollama 浜夋姠 6GB 鏄惧瓨锛夛紝
鍗曠嫭鍩哄噯浠呯害 0.3s锛涘缓璁闊虫湇鍔″父椹绘椂 ASR 鍥哄畾 CPU 鎴栨崲 base/GPU銆佸苟璁?Ollama 涓?ASR 鏄惧瓨閿欏嘲銆?
## M4.2 鍔犺浇/寤惰繜鍐插埡锛堝疄娴嬪姣旓紝璇佹嵁 `data/m4_voice/evidence_m42.json`锛?
| 鎸囨爣 | 浼樺寲鍓嶏紙鐢ㄦ埛鍙嶉/M4.1锛?| 浼樺寲鍚庯紙M4.2锛?|
| --- | --- | --- |
| 棣栨 /chat/voice 妯″瀷鍔犺浇 | ~90s锛堢敤鎴锋劅鐭?鍔犺浇澶箙"锛?| **鍚姩棰勫姞杞?0.7s**锛岄娆¤姹?ASR 浠?1.0s |
| 鏈嶅姟鍚姩鍒板彲鏈嶅姟 | 棰勫姞杞藉崱 43s锛圚F 鑱旂綉鏍￠獙瓒呮椂锛?| **0.7s**锛堟湰鍦板揩鐓х洿璇伙紝璺宠繃 HF 鏍￠獙锛?|
| 鐑€佺鍒扮 | 8.3~9.7s | 6.2~7.0s |
| 闀垮洖澶?LLM 鐢熸垚 | 14.3s / 425 瀛?| 9.3s / 52 瀛楋紙-35% / -88%锛?|

M4.2 鍥涢」浼樺寲锛?
1. **ASR 鍚姩棰勫姞杞?*锛坄ASR_PRELOAD=1` 榛樿寮€锛夛細FastAPI lifespan 鍚姩鏃跺姞杞?ASR 妯″瀷 +
   鍚庡彴棰勭儹 Ollama锛坘eep_alive锛夛紝棣栨璇煶璇锋眰闆舵ā鍨嬪姞杞界瓑寰咃紙鍚姩鏃ュ織 `[startup] ASR 妯″瀷棰勫姞杞藉畬鎴恅锛夈€?2. **鏈湴蹇収鐩磋**锛氭ā鍨嬪湪 `data/models`锛圚F 缂撳瓨甯冨眬鎴栨墎骞崇洰褰曞潎鍙級鏃剁洿鎺ユ寜璺緞鍔犺浇锛?   璺宠繃 huggingface_hub 鑱旂綉鏍￠獙鈥斺€斾慨澶嶇洿杩炶澧欐椂鐨勫惎鍔ㄥ崱椤匡紙瀹炴祴棰勫姞杞?43.2s 鈫?0.7s锛夈€?3. **ASR 榛樿璋冧紭**锛氶粯璁?`ASR_MODEL_SIZE=base` + `ASR_DEVICE=cpu` + `ASR_COMPUTE_TYPE=int8`
   锛堥摼涓婂疄娴?ASR 绋冲畾 ~0.9s锛屼笖涓嶅崰鐢?Ollama 鐨勬樉瀛橈級銆?4. **LLM 鐢熸垚闀垮害婧愬ご闄愬埗**锛歷oice 璺緞鎸?`max_reply_chars` 鏄犲皠 Ollama `num_predict`
   锛?0 瀛?鈫?162 tokens锛夛紝涓嶅啀"鍏堢敓鎴愬嚑鐧惧瓧鍐嶆埅鏂?锛堥暱鍥炲 LLM 14.3s 鈫?9.3s锛夈€?
UI锛坵eb/锛夎闊冲鐞嗕腑鍒嗛樁娈垫彁绀猴細璇嗗埆涓?鈫?TA 姝ｅ湪鎬濊€?鈫?姝ｅ湪鍚堟垚鍥炲锛岄伩鍏嶇敤鎴疯鍒ゅ崱姝汇€?
**鐑€佺鍒扮浠嶆湭杈炬爣锛?5s锛?*锛氬疄娴?6.2~7.0s锛岀摱棰堜负 LLM 鐢熸垚锛?.6~4.5s锛変笌 TTS 鍦ㄧ嚎鍚堟垚锛?.6~1.8s锛夛紱
鍚庣画鍊欓€夛細LLM 鎹?qwen2.5:3b/llama3.2:3b銆乀TS 鏈湴鍖?娴佸紡棣栧寘銆佸洖澶?鈮?0 瀛椼€?
## M4.3 璇煶 <5s 鍐插埡锛堝疄娴嬶紝璇佹嵁 `data/m4_voice/evidence_m43.json` / `evidence_m43_persona.json`锛?
**瀹炴祴鐭╅樀**锛堣繘绋嬪唴 pipeline锛欰SR base/CPU + Ollama keep_alive + edge-tts 鍦ㄧ嚎锛岀儹鎬?3 娆′腑浣嶏級锛?
| 缁勫悎 | LLM 涓綅 | 绔埌绔腑浣?|
| --- | --- | --- |
| qwen2.5:7b / 60瀛?| 4.1s | 8.5s |
| qwen2.5:7b / 40瀛?| 3.6s | 8.3s |
| llama3.2:3b / 60瀛?| 3.1s | 7.5s |
| llama3.2:3b / 40瀛?+ piper 鏈湴 TTS | **2.9s** | **4.2s** 鉁?|

**杈炬爣缁撹锛堝瀹烇級**锛?- 鉁?**鐑€佺鍒扮 <5s 杈炬垚锛堟湁鏉′欢锛?*锛歚VOICE_LLM_MODEL=llama3.2:3b` + `TTS_BACKEND=piper` + 40 瀛楅粯璁わ紝
  3 娆″疄娴?4.62/4.18/4.19s锛堜腑浣?**4.19s**锛?/3 杈炬爣锛涘垎椤?ASR 0.96s + LLM 2.88s + piper 0.36s锛夈€?- 鈿狅笍 **榛樿缁勫悎锛?b + edge-tts锛夋湭杈炬爣**锛?.5~8.5s锛夛紝鐡堕 LLM 3.6-4.1s + edge-tts 鍦ㄧ嚎 1.6-2.5s
  锛堟湰娆″疄娴嬫湡闂?edge-tts 鏈嶅姟澶氭鏂繛锛宍speech.platform.bing.com` 涓嶅彲杈锯€斺€斿湪绾?TTS 绋冲畾鎬ч闄╋級銆?- M4.3 钀藉湴锛歚VOICE_LLM_MODEL`锛堣闊充笓鐢ㄦā鍨嬶紝鏂囨湰閾捐矾涓嶅彈褰卞搷锛夈€乣TTS_BACKEND=edge_tts|piper`
  锛坧iper 鏈湴绂荤嚎涓枃闊宠壊 `data/models/piper/zh_CN-huayan-medium.onnx`锛?0 瀛楀悎鎴愮害 0.3-0.4s锛夈€?  `VOICE_MAX_REPLY_CHARS` 榛樿 60鈫?0銆?
**3b 浜鸿涓嶉€€鍖栭獙璇?*锛坙lama3.2:3b锛宑onsistency_testset 鍏抽敭 8 鏉★細T01/T03/T05/T07/T16/T18/T23/T28锛夛細
**5 PASS + 3 WARN锛? FAIL銆佹棤绾㈢嚎瑙﹀彂锛?*鈥斺€擬6 浠ｇ爜灞傛敞鍏ワ紙鑳藉姏杈圭晫/韬唤/绌鸿蹇嗛槻缂栭€?鍗辨満闄即锛夊湪 3b 涓嬪叏閮ㄧ敓鏁堬紱
WARN 椤逛负鑻辨枃璇嶅す鏉傦紙"just/talk"锛変笌 T23 鍗辨満鍥炲鏈富鍔ㄦ彁绀轰笓涓氭眰鍔┾€斺€斿缓璁敓浜х敤 3b 鏃跺湪绯荤粺鎻愮ず璇嶈ˉ涓€鍙?"绂佹澶硅嫳鏂囥€佸嵄鏈哄満鏅富鍔ㄦ彁绀轰笓涓氬府鍔?銆?
**閮ㄧ讲寤鸿锛堢敤鎴峰凡鍐崇瓥锛孧4.4 钀藉湴锛?*锛氶粯璁よ闊崇粍鍚堝凡鍒?**`llama3.2:3b + piper 鏈湴 TTS`**锛?5s 浼樺厛锛屼汉璁?WARN 鍙帴鍙楋級銆?濡傞渶鍥炲垏锛歚VOICE_LLM_MODEL=qwen2.5:7b` / `TTS_BACKEND=edge_tts`锛堝湪绾挎檽鏅撻煶璐ㄥソ浣嗗疄娴嬪娆℃柇杩烇級銆?
## M4.4 鍗辨満瀹夊叏琛ヤ竵 + 榛樿缁勫悎锛圵O-20260816-21锛岃瘉鎹?`data/m4_voice/evidence_m44_crisis.json`锛?
1. **鍗辨満姹傚姪寮曞浠ｇ爜灞傚己鍒?*锛堜笉渚濊禆 3b 閬靛惊鎻愮ず璇嶏級锛歚persona_agent` 鍗辨満鍒嗘敮锛坄is_crisis_query` 鍛戒腑锛夊湪 LLM 鍥炲鍚?   寮哄埗妫€鏌モ€斺€斿洖澶嶆湭鍚眰鍔╃嚎绱紙鐑嚎/12356/涓撲笟甯姪/瀹朵汉鏈嬪弸绛夛級鍒欒拷鍔犱汉璁惧彛鍚绘眰鍔╁彞
   銆屽鏋滀綘鎰挎剰锛屼篃鍙互鎵句俊浠荤殑瀹朵汉鎴栨湅鍙嬭亰鑱婏紝鎴栨嫧鎵撳績鐞嗘彺鍔╃儹绾匡紙濡?12356锛夛紝鎴戜竴鐩村湪銆傘€嶏紱
   LLM 宸插惈鍒欒烦杩囷紙闃查噸澶嶏紝鍗曟祴瑕嗙洊涓ゆ儏鍐碉級銆?2. **鍗辨満璇煶鍥炲涓嶆埅鏂?*锛歱ipeline 瀵瑰嵄鏈鸿矾寰勮烦杩?40 瀛楁埅鏂紝淇濊瘉姹傚姪鍙ュ畬鏁磋緭鍑猴紙瀹夊叏浼樺厛浜庡欢杩燂級銆?3. **榛樿缁勫悎鍙樻洿**锛歚VOICE_LLM_MODEL` 榛樿 `llama3.2:3b`銆乣TTS_BACKEND` 榛樿 `piper`銆?4. **3b 鍗辨満鐪熷疄 smoke锛坙lama3.2:3b锛? 鏉★級**锛氬叏閮ㄥ惈涓撲笟姹傚姪寮曞鈥斺€擫LM 宸插惈锛?2356/瀹朵汉鏈嬪弸锛夆啋 涓嶉噸澶嶏紱
   LLM 鏈惈 鈫?浠ｇ爜灞傝拷鍔犮€傝瘉鎹 `data/m4_voice/evidence_m44_crisis.json`銆?
**piper 涓枃妯″瀷涓嬭浇锛坓itignored锛屾柊鍏嬮殕闇€鎵嬪姩鍑嗗锛?*锛?
```powershell
pip install piper-tts
New-Item -ItemType Directory -Force -Path data/models/piper | Out-Null
curl -L -o data/models/piper/zh_CN-huayan-medium.onnx "https://hf-mirror.com/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx"
curl -L -o data/models/piper/zh_CN-huayan-medium.onnx.json "https://hf-mirror.com/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx.json"
```

> 宸茬煡椤癸紙濡傚疄锛夛細3b 涓枃浜鸿鍋跺彂澶硅嫳鏂囷紙濡?"cool/talked-through"锛変笖椋庢牸鐣ラ鈥斺€斿嵄鏈哄畨鍏ㄤ笉鍙楀奖鍝嶏紙浠ｇ爜灞傚厹搴曪級锛?> 鏃ュ父鍙ｈ璐ㄩ噺寤鸿鍚庣画鐢?qwen2.5:3b锛堝緟缃戠粶鐜琛ユ媺锛夋垨鎻愮ず璇嶈ˉ"绂佹澶硅嫳鏂?銆?
## 娴嬭瘯

```powershell
python -m pytest -q        # 鍏ㄩ儴绂荤嚎锛歮ock ASR/TTS 涓庡閮ㄦ湇鍔★紙瑙勫垝/鏃ョ▼ Agent 浜?mock LLM锛?```

- Web 鐣岄潰锛圡5锛夛細`tests/test_web_ui.py`锛堥椤佃矾鐢?/ 闈欐€佹寕杞?/ 鏃㈡湁 API 鍥炲綊鎶ゆ爮锛夈€?- 婕旂ず娴佺▼锛氳 `docs/婕旂ず鑴氭湰.md`锛堝彲鐓у仛鐨?6 姝ユ紨绀?+ 棰勬湡鏁堟灉 + 鎴浘鎸囧紩锛夈€?
## 鐩稿叧鏂囨。

- 婕旂ず鑴氭湰锛歚docs/婕旂ず鑴氭湰.md`锛涜鑹蹭竴鑷存€ц瘎娴嬶細`docs/consistency_testset.md`锛圡6锛?- 浜у搧瀹氫箟 / 鎶€鏈€夊瀷 / 閲岀▼纰戣鍒掞細`30 路 椤圭洰/AI铏氭嫙浜虹墿/`锛堢煡璇嗗簱锛?- 棰嗗煙鐭ヨ瘑锛歚20 路 宸ヤ綔棰嗗煙/`锛堢煡璇嗗簱锛?
## M6.1 工具调用（LLM function calling，WO-20260816-29）

人格 Agent 支持 LLM 自主调用工具（qwen2.5:7b 原生 tool calling，两阶段：无人设工具决策 → 人设包装回复）：

- **工具集**（app/tools/tool_specs.py）：add_schedule / get_schedule / query_memory / query_knowledge / calculate / list_plans
- **对话示例**：『明天下午3点提醒我喝水』→ LLM 自主调用 add_schedule；『你记得我喜欢什么吗』→ query_memory（向量检索）
- **开关**：TOOL_CALLING_ENABLED（默认 1）；关闭后回退到 M5.1 关键词路由（原逻辑不变）
- **安全**：危机分支最高优先（不经工具）；工具调用失败/未命中 → 自动回退关键词路由（确定性操作不丢）
- 证据：data/m6_1/evidence_tool_calling.json
