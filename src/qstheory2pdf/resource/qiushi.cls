% qiushi.cls — LaTeX class for qstheory2pdf (forked from ElegantNote)
% Upstream author: Dongsheng Deng (ElegantLaTeX/ElegantNote)
%
% 2026-07 revision:
%   * Cross-platform Chinese font auto-detection — no more manual/sed
%     fontset switching. Priority: Windows (SimSun) > macOS (Songti SC)
%     > Noto CJK (Linux/CI, FULL rare-glyph coverage: 祎/頔/赟/曌 …)
%     > Fandol (last resort; limited GBK coverage).
%   * New "qiushi" color theme (deep red accent) used on LCD/paper
%     devices; e-ink devices keep pure black.
%   * Typographic polish: heiti headlines, fangsong bylines, short rule
%     ornaments, quieter header/footer, magazine-style TOC macros.
%   * Removed unused biblatex hooks (no bibliography in this pipeline).

% --- Class structure: identification part
\ProvidesClass{qiushi}[2026/07/26 QiuShi v0.2 class]
\NeedsTeXFormat{LaTeX2e}


\RequirePackage{kvoptions}
\RequirePackage{etoolbox}
\RequirePackage{calc}

\SetupKeyvalOptions{family=ELEGANT,prefix=ELEGANT@,setkeys=\kvsetkeys}
\newcommand{\ekv}[1]{\kvsetkeys{ELEGANT}{#1}}

\DeclareStringOption[qiushi]{color}
\DeclareVoidOption{black}{\ekv{color=black}}
\DeclareVoidOption{qiushi}{\ekv{color=qiushi}}

\DeclareStringOption[pad]{device}
\DeclareVoidOption{pc}{\ekv{device=pc}}
\DeclareVoidOption{pad}{\ekv{device=pad}}
\DeclareVoidOption{kindle}{\ekv{device=kindle}}
\DeclareVoidOption{normal}{\ekv{device=normal}}
\DeclareVoidOption{screen}{\ekv{device=screen}}
\DeclareVoidOption{scribe}{\ekv{device=scribe}}

\DeclareStringOption[cn]{lang}
\DeclareVoidOption{cn}{\ekv{lang=cn}}

\DeclareStringOption{mode}

\DeclareStringOption[ctexfont]{chinesefont}
\DeclareVoidOption{ctexfont}{\ekv{chinesefont=ctexfont}}
\DeclareVoidOption{wenkai}{\ekv{chinesefont=wenkai}}

\DeclareStringOption[11pt]{fontsize}
\DeclareVoidOption{11pt}{\ekv{fontsize=11pt}}

\DeclareStringOption[cm]{math}
\DeclareVoidOption{cm}{\ekv{math=cm}}

\DeclareDefaultOption{
  \PassOptionsToClass{\CurrentOption}{article}
 }
\ProcessKeyvalOptions*\relax

\LoadClass{article}

\PassOptionsToPackage{no-math}{fontspec}
\PassOptionsToPackage{quiet}{fontspec}
\RequirePackage{amsmath,amsthm}

\RequirePackage{iftex}

\ifXeTeX
  \RequirePackage[no-math]{fontspec}
  \setmainfont{texgyretermes}[
    UprightFont = *-regular ,
    BoldFont = *-bold ,
    ItalicFont = *-italic ,
    BoldItalicFont = *-bolditalic ,
    Extension = .otf ,
    Scale = 1.0]

  \setsansfont{texgyreheros}[
    UprightFont = *-regular ,
    BoldFont = *-bold ,
    ItalicFont = *-italic ,
    BoldItalicFont = *-bolditalic ,
    Extension = .otf ,
    Scale = 0.9]
\else
  \RequirePackage{newtxtext}
  \RequirePackage[scaled=.90]{helvet}
\fi



\ifdefstring{\ELEGANT@lang}{cn}{
  % ================================================================
  % 字体策略：开源字体优先，三端（Windows/macOS/Linux·CI）输出一致
  %
  %   探测顺序（chinesefont=ctexfont，默认）：
  %     1. 开源组合：思源宋体/Noto Serif（正文）+ 思源黑体/Noto Sans
  %        （标题）+ 霞鹜文楷（楷体，作者/图注/引文）
  %        —— 生僻字全覆盖（祎/頔/赟/曌…），装了这些字体即用
  %     2. 回退 Windows 系统字体（SimSun 等）
  %     3. 回退 macOS 系统字体（Songti SC 等）
  %     4. 兜底 Fandol（TeX Live 自带；生僻字覆盖有限）
  %
  %   chinesefont=wenkai：全文使用霞鹜文楷（含西文），适合休闲阅读；
  %   未安装文楷时告警并回退到上面的自动探测。
  % ================================================================
  %
  % ---- 探测开源字体（Noto 与思源为同一字体的两种发行名）----
  \IfFontExistsTF{Noto Serif CJK SC}{\def\qs@song{Noto Serif CJK SC}}{%
    \IfFontExistsTF{Source Han Serif SC}{\def\qs@song{Source Han Serif SC}}{%
      \def\qs@song{}}}
  \IfFontExistsTF{Noto Sans CJK SC}{\def\qs@hei{Noto Sans CJK SC}}{%
    \IfFontExistsTF{Source Han Sans SC}{\def\qs@hei{Source Han Sans SC}}{%
      \def\qs@hei{}}}
  \IfFontExistsTF{LXGW WenKai}{\def\qs@kai{LXGW WenKai}}{%
    \IfFontExistsTF{LXGW WenKai GB}{\def\qs@kai{LXGW WenKai GB}}{%
      \IfFontExistsTF{FandolKai}{\def\qs@kai{FandolKai}}{\def\qs@kai{}}}}

  % ---- wenkai 模式前置检查：未装文楷则回退自动 ----
  \ifdefstring{\ELEGANT@chinesefont}{wenkai}{%
    \IfFontExistsTF{LXGW WenKai}{\relax}{%
      \IfFontExistsTF{LXGW WenKai GB}{\relax}{%
        \ClassWarningNoLine{qiushi}{chinesefont=wenkai but LXGW WenKai not
          found; falling back to automatic font detection}%
        \ekv{chinesefont=ctexfont}}}}{\relax}

  % ---- 全文楷模式 ----
  \ifdefstring{\ELEGANT@chinesefont}{wenkai}{%
    \RequirePackage[UTF8,scheme=plain,fontset=none]{ctex}%
    \IfFontExistsTF{LXGW WenKai}{\def\qs@wk{LXGW WenKai}}{\def\qs@wk{LXGW WenKai GB}}%
    \IfFontExistsTF{LXGW WenKai Medium}{\def\qs@wkm{LXGW WenKai Medium}}{\edef\qs@wkm{\qs@wk}}%
    \IfFontExistsTF{LXGW WenKai Light}{\def\qs@wkl{LXGW WenKai Light}}{\edef\qs@wkl{\qs@wk}}%
    % 西文一并用文楷，风格统一（文楷的西文来自 Klee One，观感很好）
    \setmainfont[BoldFont={\qs@wkm}]{\qs@wk}%
    \setCJKmainfont[BoldFont={\qs@wkm}]{\qs@wk}%
    \setCJKsansfont{\qs@wkm}%
    \setCJKmonofont{\qs@wk}%
    \setCJKfamilyfont{zhsong}[BoldFont={\qs@wkm}]{\qs@wk}%
    \setCJKfamilyfont{zhhei}{\qs@wkm}%
    \setCJKfamilyfont{zhkai}{\qs@wk}%
    \setCJKfamilyfont{zhfs}{\qs@wkl}%
    \providecommand{\songti}{\CJKfamily{zhsong}}%
    \providecommand{\heiti}{\CJKfamily{zhhei}}%
    \providecommand{\kaishu}{\CJKfamily{zhkai}}%
    \providecommand{\fangsong}{\CJKfamily{zhfs}}%
  }{\relax}

  % ---- 自动探测模式（默认）----
  \ifdefstring{\ELEGANT@chinesefont}{ctexfont}{%
    \ifdefempty{\qs@song}{%
      % 开源宋体缺失 → 回退系统字体 / Fandol
      \IfFontExistsTF{SimSun}{\def\qs@fontset{windows}}{%
        \IfFontExistsTF{Songti SC}{\def\qs@fontset{mac}}{%
          \def\qs@fontset{fandol}}}%
      \RequirePackage[UTF8,scheme=plain,fontset=\qs@fontset]{ctex}%
      \providecommand{\songti}{\CJKfamily{zhsong}}%
      \providecommand{\heiti}{\CJKfamily{zhhei}}%
      \providecommand{\kaishu}{\CJKfamily{zhkai}}%
      \providecommand{\fangsong}{\CJKfamily{zhfs}}%
    }{%
      % 开源组合（首选）
      \RequirePackage[UTF8,scheme=plain,fontset=none]{ctex}%
      \ifdefempty{\qs@hei}{\edef\qs@hei{\qs@song}}{\relax}%
      \ifdefempty{\qs@kai}{%
        \IfFontExistsTF{Noto Serif CJK SC Light}%
          {\def\qs@kai{Noto Serif CJK SC Light}}{\edef\qs@kai{\qs@song}}}{\relax}%
      \IfFontExistsTF{FandolFang}{\def\qs@fs{FandolFang}}{\edef\qs@fs{\qs@kai}}%
      \setCJKmainfont{\qs@song}%
      \setCJKsansfont{\qs@hei}%
      \IfFontExistsTF{Noto Sans Mono CJK SC}%
        {\setCJKmonofont{Noto Sans Mono CJK SC}}{\setCJKmonofont{\qs@hei}}%
      \setCJKfamilyfont{zhsong}{\qs@song}%
      \setCJKfamilyfont{zhhei}{\qs@hei}%
      \setCJKfamilyfont{zhkai}{\qs@kai}%
      \setCJKfamilyfont{zhfs}{\qs@fs}%
      \providecommand{\songti}{\CJKfamily{zhsong}}%
      \providecommand{\heiti}{\CJKfamily{zhhei}}%
      \providecommand{\kaishu}{\CJKfamily{zhkai}}%
      \providecommand{\fangsong}{\CJKfamily{zhfs}}%
    }}{\relax}

  \AfterEndPreamble{
    \setlength\parindent{2\ccwd}%
    \setlength\emergencystretch{3\ccwd}}
}{\relax}

\ifcsname kaishu\endcsname
  \newcommand{\citshape}{\kaishu}
\else
  \newcommand{\citshape}{\itshape}
\fi
\ifcsname kaishu\endcsname
  \newcommand{\cnormal}{\kaishu}
\else
  \newcommand{\cnormal}{\normalfont}
\fi
\ifcsname fangsong\endcsname
  \newcommand{\cfs}{\fangsong}
\else
  \newcommand{\cfs}{\normalfont}
\fi

\RequirePackage{appendix}

\ifdefstring{\ELEGANT@lang}{cn}{%
  \theoremstyle{plain}% default
  \newtheorem{theorem}{定理}[section] %
  \newtheorem{lemma}[theorem]{引理} %
  \newtheorem{proposition}[theorem]{命题} %
  \newtheorem*{corollary}{推论} %
  \theoremstyle{definition} %
  \newtheorem{definition}{定义}[section] %
  \newtheorem{conjecture}{猜想}[section] %
  \newtheorem{example}{例}[section] %
  \theoremstyle{remark} %
  \newtheorem*{remark}{\normalfont\bfseries 评论} %
  \newtheorem*{note}{\normalfont\bfseries 注} %
  \newtheorem{case}{\normalfont\bfseries 案例} %
  \renewcommand*{\proofname}{\normalfont\bfseries\color{ecolor}证明} %
  \renewcommand\contentsname{\color{ecolor}目录}
  \renewcommand\refname{\color{ecolor}参考文献} %
  \renewcommand\figurename{图} %
  \renewcommand\tablename{表}
  \newcommand\versiontext{版本：}%
  \newcommand\updatetext{来源：}%
  \setlength{\parindent}{2em}
  \newcommand{\keywords}[1]{%
    \vskip2ex\par\noindent\normalfont{\bfseries 关键词: } #1}
  }{\relax}

\RequirePackage{indentfirst}
\RequirePackage{anyfontsize}

\RequirePackage{graphicx}
\RequirePackage{booktabs}
\let\openbox\relax

\RequirePackage{xcolor}
\definecolor{winered}{rgb}{0.5,0,0}
\definecolor{qsgray}{RGB}{110,110,110}

\RequirePackage{hyperref}
\RequirePackage{xpatch}
\hypersetup{%
  pdfborder={0 0 0},
  colorlinks,
  citecolor=ecolor,
  filecolor=ecolor,
  linkcolor=ecolor,
  urlcolor=ecolor
}

\RequirePackage{hologo}

% 行距设置
% Chinese convention: paragraph structure is carried by the 2em/2\ccwd
% first-line indent; keep only a small flexible parskip. Widow/orphan
% penalties matter on small e-reader pages; \raggedbottom avoids parskip
% being stretched into ugly vertical gaps when images force page breaks.
\linespread{1.3}
\setlength{\parskip}{0.4em plus 0.2em minus 0.1em}
\setlength{\parindent}{2em}
\widowpenalty=10000
\clubpenalty=10000
\raggedbottom
\RequirePackage{silence}

% 护眼模式
\ifdefstring{\ELEGANT@mode}{geye}{
  \definecolor{geyecolor}{RGB}{199,237,204}%
  \pagecolor{geyecolor}
}{\relax}
\ifdefstring{\ELEGANT@mode}{hazy}{
  \definecolor{geyecolor}{RGB}{251,250,248}%
  \pagecolor{geyecolor}
}{\relax}
\ifdefstring{\ELEGANT@mode}{sepia}{
  \definecolor{geyecolor}{RGB}{250,237,225}%
  \pagecolor{geyecolor}
}{\relax}


% graphics path
\graphicspath{
  {./figure/}
  {./figures/}
  {./image/}
  {./images/}
  {./graphics/}
  {./graphic/}
  {./pictures/}
  {./picture/}
}

\let\openbox\relax
\newtheoremstyle{plain}{\topsep}{\topsep}{\citshape}{}{%
  \color{ecolor}\bfseries}{}{%
  0.5em}{%
  \thmname{#1}\thmnumber{ #2}\thmnote{ (#3)}}

\newtheoremstyle{definition}{\topsep}{\topsep}{\citshape}{}{%
  \color{ecolor}\bfseries}{}{%
  0.5em}{}

\newtheoremstyle{remark}{\topsep}{\topsep}{\cnormal}{}{
  \color{ecolor}\bfseries}{}{
  0.5em}{}

% caption settings
\RequirePackage{caption}
\captionsetup{
  labelfont={bf,color=ecolor}}
\captionsetup[table]{skip=3pt}
% black captions: colored text dithers to muddy gray on e-ink displays
\captionsetup[figure]{skip=3pt, font={footnotesize, color=black}}

% list/itemize/enumerate setting
\RequirePackage[shortlabels,inline]{enumitem}
\setlist{nolistsep}

\RequirePackage[flushmargin,stable]{footmisc}
\setlength{\footnotesep}{12pt}

\RequirePackage{titlesec}
\titleformat*{\section}{\normalfont\Large\heiti\bfseries\color{ecolor}}
\titleformat*{\subsection}{\normalfont\large\heiti\bfseries\color{ecolor}}
\titleformat*{\subsubsection}{\normalfont\normalsize\heiti\bfseries\color{ecolor}}

% ---- color themes ----------------------------------------------------
% qiushi: deep magazine red for LCD/paper reading; black: pure black,
% for e-ink devices where color dithers to muddy gray.
\ifdefstring{\ELEGANT@color}{qiushi}{
  \definecolor{ecolor}{RGB}{166,27,31}%
}{\relax}
\ifdefstring{\ELEGANT@color}{black}{
  \definecolor{ecolor}{RGB}{0,0,0}%
}{\relax}
% legacy option value kept working (ElegantNote heritage)
\ifdefstring{\ELEGANT@color}{blue}{
  \definecolor{ecolor}{RGB}{1,126,218}%
}{\relax}
\providecolor{ecolor}{RGB}{0,0,0}

%% device settings
%% default=pad

\RequirePackage{geometry}
% scribe: default to 12pt for comfortable e-ink reading unless the user
% passed an explicit fontsize (note: an explicit fontsize=11pt cannot be
% distinguished from the default; pass 10pt if you want smaller).
\ifdefstring{\ELEGANT@device}{scribe}{%
  \ifdefstring{\ELEGANT@fontsize}{11pt}{\def\ELEGANT@fontsize{12pt}}{\relax}}{\relax}
\WarningsOff
\RequirePackage[\ELEGANT@fontsize]{extsizes}
\WarningsOn

\ifdefstring{\ELEGANT@device}{pad}{%
  \geometry{
    paperwidth=6in,
    paperheight=8in,
    includefoot,
    headheight=15pt,
    margin=8mm}}{%
  \relax}

\ifdefstring{\ELEGANT@device}{pc}{
  \geometry{%
    margin=8mm,
    headheight=15pt,
    paperwidth=6.2in,
    paperheight=6in,
    includefoot}}{%
  \relax}

\ifdefstring{\ELEGANT@device}{kindle}{%
  \geometry{
    margin=8mm,
    headheight=15pt,
    paperwidth=3.68in,
    paperheight=4.92in}}{%
  \relax}

% A4: slightly wider side margins and asymmetric top/bottom for a calmer
% page; includehead keeps the running head out of the text block.
\ifdefstring{\ELEGANT@device}{normal}{%
  \geometry{
    a4paper,
    hmargin=2.6cm,
    top=2.4cm,
    bottom=2.8cm,
    headheight=16pt,
    headsep=0.7cm,
    footskip=1.2cm}}{%
  \relax}

\ifdefstring{\ELEGANT@device}{screen}{%
  \geometry{
    screen,
    paperwidth=25.4cm,
    paperheight=19.05cm,
    margin=1.6cm,
    headheight=2.3cm,
    footskip=0.6cm}}{%
  \relax}

\ifdefstring{\ELEGANT@device}{scribe}{%
  \geometry{
    margin=8mm,
    headheight=15pt,
    paperwidth=5.83in,
    paperheight=7.76in,
    includefoot}
  % generous leading is the biggest readability lever on e-ink; CJK glyphs
  % fill the em-box, so 1.3 reads tight at this measure
  \linespread{1.4}}{%
  \relax}

% headings
\RequirePackage{fancyhdr}
\renewcommand{\footrulewidth}{0pt}

\def\issuevolume{}

% Header rule only when there is header content (issue mode); single
% articles previously got a stray bare rule at the top of every page.
\renewcommand{\headrulewidth}{\ifx\issuevolume\empty 0pt\else 0.3pt\fi}

\fancypagestyle{fancy-note}{
  \fancyhf{} % clear header/footer settings
  \fancyfoot[C]{\footnotesize\color{qsgray}— \thepage\ —}
  \ifx\issuevolume\empty
    \fancyhead[C]{}
  \else
    \fancyhead[C]{\footnotesize\kaishu\color{qsgray}\issuevolume}
  \fi
}

\fancypagestyle{plain}{%
  \fancyhf{}
  \renewcommand{\headrulewidth}{0pt}%
  \fancyfoot[C]{\footnotesize\color{qsgray}— \thepage\ —}}

\pagestyle{fancy-note}

% ---- article title furniture (used by gen_pdf.py) --------------------
% 栏目 tag, headline, subtitle, byline, closing rule, and in-body
% section heading. Centralized here so every device/theme renders a
% consistent title block.
\newcommand{\qscolumn}[1]{%
  {\centering\small\kaishu\color{ecolor}〔#1〕\par}}
\newcommand{\qstitle}[1]{%
  {\centering\LARGE\heiti\bfseries #1\par}}
\newcommand{\qssubtitle}[1]{%
  {\centering\large\kaishu\color{qsgray}#1\par}}
\newcommand{\qsauthor}[1]{%
  {\centering\normalsize\fangsong #1\par}}
\newcommand{\qstitlerule}{%
  {\centering\color{ecolor}\rule{3.5em}{0.18em}\par}}
% magazine-style centered section heading inside the body
\newcommand{\qsheading}[1]{%
  \par\vspace{1.1em plus 0.3em}%
  {\centering\heiti\Large\color{ecolor}#1\par}%
  \vspace{0.55em plus 0.2em}}

% ---- TOC furniture ----------------------------------------------------
\newcommand{\qstocheader}{%
  {\centering\Huge\heiti\bfseries 目\quad 录\par}%
  \vspace{0.5em}%
  {\centering\color{ecolor}\rule{0.62\textwidth}{0.14em}\par}%
  \vspace{1.6em}}
\newcommand{\qstoccolumn}[1]{%
  \par\vspace{1.1em plus 0.2em}%
  \noindent{\color{ecolor}\rule[-0.28em]{0.28em}{1.15em}}\hspace{0.55em}%
  {\large\heiti\color{ecolor}#1}\par
  \vspace{0.55em}}
% dotted leader that is lighter than \dotfill
\newcommand{\qstocdots}{%
  \leaders\hbox to 0.62em{\hss\textcolor{qsgray}{·}\hss}\hfill}


\def\IfEmpty#1{%
  \edef\1{\the#1}
  \ifx\1\empty}

\newtoks\version
\newtoks\institute

\def \ifempty#1{
  \def\temp{#1}
  \ifx\temp\empty}

\renewcommand\maketitle{\par
  \begingroup
    \renewcommand\thefootnote{\@fnsymbol\c@footnote}%
    \def\@makefnmark{\rlap{\@textsuperscript{\normalfont\@thefnmark}}}%
    \long\def\@makefntext##1{\parindent 1em\noindent
         \hb@xt@1.8em{%
           \hss\@textsuperscript{\normalfont\@thefnmark}}##1}%
    \if@twocolumn
      \ifnum \col@number=\@ne
        \@maketitle
      \else
        \twocolumn[\@maketitle]%
      \fi
    \else
      \newpage
      \global\@topnum\z@  % Prevents figures from going at top of page.
      \@maketitle
    \fi
    \thispagestyle{empty}\@thanks
  \endgroup
  \setcounter{footnote}{0}%
  \global\let\thanks\relax
  \global\let\maketitle\relax
  \global\let\@maketitle\relax
  \global\let\@thanks\@empty
  \global\let\@author\@empty
  \global\let\@date\@empty
  \global\let\@title\@empty
  \global\let\title\relax
  \global\let\author\relax
  \global\let\date\relax
  \global\let\and\relax}

% single-article title block: heiti headline in theme color, short red
% rule, fangsong byline, kai source line — mirrors the issue-mode design.
\def\@maketitle{%
  \null
  \vskip 1.6em%
  \begin{center}%
    {\LARGE\heiti\bfseries\color{ecolor}\@title\par}%
    \vskip 0.9em%
    {\color{ecolor}\rule{3.5em}{0.18em}\par}%
    \ifx\@author\@empty\else
      \vskip 0.9em%
      {\normalsize\fangsong\@author\par}%
    \fi
    \ifx\@date\@empty\else
      \vskip 0.45em%
      {\small\kaishu\color{qsgray}来源：\@date\par}%
    \fi
  \end{center}%
  \vskip 0.8em%
  \par}


\RequirePackage{tikz}
\usetikzlibrary{shadows}
\newcommand*{\eitemi}{
  \tikz\draw[baseline, ball color=ecolor, draw=none] circle (2pt);}
\newcommand*{\eitemii}{
  \tikz\draw[baseline, fill=ecolor,draw=none,circular drop shadow] circle (2pt);}
\newcommand*{\eitemiii}{%
  \tikz\draw[baseline,fill=ecolor,draw=none] circle (2pt);}

% add qrcode at the page's bottom-right corner (the title page uses
% \thispagestyle{empty}, so this corner is guaranteed free; the old
% top-right position collided with the \maketitle title on small pages)
\newcommand{\qrcode}[1]{%
  \ifblank{#1}{}{%
    \tikz[remember picture,overlay]
      \path (current page.south east) ++ (-1.6,1.6)
        node {\includegraphics[width=1.5cm]{#1}};}%
}



\setlist[enumerate,1]{label=\color{ecolor}\arabic*.}
\setlist[enumerate,2]{label=\color{ecolor}(\alph*).}
\setlist[enumerate,3]{label=\color{ecolor}\Roman*.}
\setlist[enumerate,4]{label=\color{ecolor}\Alph*.}
\setlist[itemize,1]{label={\eitemi}}
\setlist[itemize,2]{label={\eitemii}}
\setlist[itemize,3]{label={\eitemiii}}
