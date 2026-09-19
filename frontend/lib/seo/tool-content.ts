import type { ToolId } from "@/lib/tools";

/**
 * Long-form, server-rendered copy for each tool route.
 *
 * Why this exists: every tool *workspace* is loaded with `ssr: false` (it reads `File`
 * objects and renders to canvas, so it cannot be server-rendered). That left every tool
 * page serving ~13 words of HTML and no heading at all — they are the pages that should
 * rank for "merge pdf", "compress pdf" and friends. This module is the crawlable half of
 * those pages: `ToolSeoSection` renders it on the server, below the workspace.
 *
 * `title` lives here rather than in `lib/tools.ts` because it is search copy, not a UI
 * label — `tool.name` is still what the header, cards and buttons show.
 */
export interface ToolSeo {
  /** The `<title>`, minus the "| PDFKit" suffix the root template appends. Aim 40-58 total. */
  title: string;
  /** The page's single server-rendered `h1`. Phrased for search, not as a button label. */
  h1: string;
  /** Heading over the step list. Spelled out rather than derived, so each one reads well. */
  howTo: string;
  /** Lead paragraphs under the h1. */
  intro: string[];
  /** Rendered as an ordered list. Describes the real flow of the tool. */
  steps: { title: string; body: string }[];
  /** Rendered as a definition list and emitted as FAQPage structured data. */
  faqs: { q: string; a: string }[];
}

export const TOOL_SEO: Record<ToolId, ToolSeo> = {
  merge: {
    title: "Merge PDF Files Online, Free and Private",
    h1: "Merge PDF files",
    howTo: "How to merge PDF files",
    intro: [
      "Merge PDF joins two or more PDFs into one document, in the order you set. Drag the files into position, then build the combined file in a single click.",
      "The merge runs inside this browser tab using pdf-lib. Your files are never uploaded, so there is no size cap beyond what your own machine can hold, and nothing to delete afterwards.",
    ],
    steps: [
      {
        title: "Select your PDFs",
        body: "Drop the files onto the page or use the file picker. Add as many as you need; you can always add more later.",
      },
      {
        title: "Put them in order",
        body: "Drag the cards to rearrange them, or sort by name or size. The first card becomes the first page of the result.",
      },
      {
        title: "Merge and download",
        body: "Press Merge PDF. The combined document is written in the tab and downloads straight away.",
      },
    ],
    faqs: [
      {
        q: "Do my files get uploaded anywhere?",
        a: "No. Merging happens in your browser with pdf-lib, so the PDFs stay on your computer for the whole job.",
      },
      {
        q: "Is there a limit on how many files I can merge?",
        a: "There is no fixed limit. Large jobs are bound by your device's memory rather than by a server quota.",
      },
      {
        q: "Will merging change the quality of my pages?",
        a: "No. Pages are copied across as they are, so text stays selectable and images keep their original resolution.",
      },
      {
        q: "Can I merge a password-protected PDF?",
        a: "Not directly. Remove the password with Unlock PDF first, then merge the result.",
      },
    ],
  },

  split: {
    title: "Split a PDF into Separate Pages or Ranges",
    h1: "Split a PDF",
    howTo: "How to split a PDF",
    intro: [
      "Split PDF cuts one document into page ranges or single pages. Enter the ranges you want, see which pages land in each file, then download one PDF or a zip of several.",
      "Splitting runs in your browser. The file is read locally and the new PDFs are written locally, so nothing is sent to a server.",
    ],
    steps: [
      {
        title: "Choose a file",
        body: "Drop in one PDF. The tool reads its page count, so ranges can be checked against the real document as you type.",
      },
      {
        title: "Set the ranges",
        body: "Enter ranges such as 1-3, 7, 9-12, or switch to fixed-size chunks or one file per page.",
      },
      {
        title: "Download the result",
        body: "A single range downloads as one PDF. Several ranges download together as a zip.",
      },
    ],
    faqs: [
      {
        q: "Can I split a PDF without uploading it?",
        a: "Yes. This tool reads and writes the file entirely in the browser tab, so the PDF never leaves your computer.",
      },
      {
        q: "How do I pull one page out of a PDF?",
        a: "Enter that page number on its own as the only range. The result is a single-page PDF.",
      },
      {
        q: "What happens to bookmarks and form fields?",
        a: "Page content, text and images carry over. Document-level features such as bookmarks and form data are not preserved in the split files.",
      },
      {
        q: "Can I get every page as its own file?",
        a: "Yes. Choose the option to split into single pages and the result arrives as a zip with one PDF per page.",
      },
    ],
  },

  organize: {
    title: "Organize PDF Pages: Reorder, Rotate, Delete",
    h1: "Organize PDF pages",
    howTo: "How to organize PDF pages",
    intro: [
      "Organize PDF shows every page as a thumbnail, so you can drag pages into a new order, rotate the ones that are sideways, and delete the ones you do not want. Pages from more than one PDF can share the same grid.",
      "All of it happens in the browser: thumbnails are rendered with pdf.js and the new document is written with pdf-lib, on your machine.",
    ],
    steps: [
      {
        title: "Add one or more PDFs",
        body: "Every page from every file appears in one grid, tagged with the file it came from.",
      },
      {
        title: "Rearrange the grid",
        body: "Drag pages into place, rotate any page a quarter turn at a time, and remove the ones you do not need.",
      },
      {
        title: "Build the new PDF",
        body: "Press Organize PDF to write the pages out in their new order.",
      },
    ],
    faqs: [
      {
        q: "Can I combine pages from different PDFs?",
        a: "Yes. Add several files and their pages share a single grid, so you can interleave them however you like.",
      },
      {
        q: "How do I delete a page from a PDF?",
        a: "Remove it from the grid. Deleted pages are simply left out of the document that gets written, and the original file on disk is untouched.",
      },
      {
        q: "Does rotating here change the page content?",
        a: "No. Rotation is stored as a page attribute, so the text and images are untouched and stay selectable.",
      },
      {
        q: "Is anything uploaded while I organize?",
        a: "No. Both the thumbnail rendering and the final write run in this tab.",
      },
    ],
  },

  rotate: {
    title: "Rotate PDF Pages and Save the Result",
    h1: "Rotate PDF pages",
    howTo: "How to rotate PDF pages",
    intro: [
      "Rotate PDF turns pages the right way up and saves the rotation into the file, so it opens correctly everywhere instead of only in the viewer where you rotated the view.",
      "Rotate every page of every file at once, or set a different angle per file. The work happens in your browser.",
    ],
    steps: [
      {
        title: "Add your PDFs",
        body: "Drop in one file or several. Each one gets a thumbnail, so you can see which way it currently faces.",
      },
      {
        title: "Pick an angle",
        body: "Rotate a quarter turn either way or a half turn, for everything at once or file by file.",
      },
      {
        title: "Save the rotated file",
        body: "Press Rotate PDF and download. One file downloads as a PDF; several download as a zip.",
      },
    ],
    faqs: [
      {
        q: "Why does my PDF look rotated in one app but not another?",
        a: "Some viewers let you rotate the view without saving it. This tool writes the rotation into the file itself, so every viewer honours it.",
      },
      {
        q: "Can I rotate just one page?",
        a: "Use Organize PDF instead. It shows every page separately and lets you rotate each one on its own.",
      },
      {
        q: "Does rotating reduce quality?",
        a: "No. Nothing is re-rendered; only the page's rotation attribute changes.",
      },
      {
        q: "Are my files uploaded?",
        a: "No. Rotation runs in the browser tab and the file stays on your computer.",
      },
    ],
  },

  "page-numbers": {
    title: "Add Page Numbers to a PDF Online, Free",
    h1: "Add page numbers to a PDF",
    howTo: "How to add page numbers to a PDF",
    intro: [
      "Page numbers stamps a number onto every page of a PDF, in the corner or centre you choose. Set the margin, the starting number, the font and the format, and watch the position on a live preview before you commit.",
      "The stamping is done in the browser with pdf-lib, so the document stays on your computer.",
    ],
    steps: [
      {
        title: "Add a PDF",
        body: "Drop in one file or several. Each file is numbered on its own.",
      },
      {
        title: "Choose position and format",
        body: "Pick one of the nine positions, set the margin and the starting number, and choose a format such as a plain number or Page 1 of 10.",
      },
      {
        title: "Stamp and download",
        body: "Press Add page numbers to write the numbers in and download the result.",
      },
    ],
    faqs: [
      {
        q: "Can I start numbering at something other than 1?",
        a: "Yes. Set the starting number and the count runs from there, which is what you want when the PDF is one section of a longer document.",
      },
      {
        q: "Can I leave the cover page unnumbered?",
        a: "Split the cover off with Split PDF, number the rest, then merge the two back together with Merge PDF.",
      },
      {
        q: "Which formats are available?",
        a: "A plain number, Page N, and Page N of M, in your choice of font and size.",
      },
      {
        q: "Will the number cover up my content?",
        a: "The number sits in the margin you choose. Increase the margin if your page content runs close to the edge.",
      },
    ],
  },

  compress: {
    title: "Compress PDF: Reduce PDF File Size Online",
    h1: "Compress a PDF",
    howTo: "How to compress a PDF",
    intro: [
      "Compress PDF reduces the size of a document so it fits an email or an upload limit. Three levels let you trade size against fidelity, and the result screen reports exactly how much each file saved.",
      "Compression needs tools that do not run in a browser, so this one sends the file to the server, processes it and deletes it within the same request. Files are capped at 50 MB each.",
    ],
    steps: [
      {
        title: "Add your PDFs",
        body: "Drop in one file or several, up to 50 MB each.",
      },
      {
        title: "Pick a compression level",
        body: "Low keeps the most detail and high gives the smallest file. The recommended level sits in between and suits most documents.",
      },
      {
        title: "Compress and download",
        body: "Each file reports its old and new size, so you can see what you gained before you download.",
      },
    ],
    faqs: [
      {
        q: "How much smaller will my PDF get?",
        a: "It depends what is inside it. Scans and image-heavy documents often shrink by half or more. Word documents that embed their fonts whole — a single emoji can drag in several megabytes of font — can lose almost everything, sometimes 98%. Documents made of vector drawing, such as anything printed through a Print to PDF driver, typically lose about a quarter. A file that is already lean may barely change, and the result screen tells you when that happens rather than claiming a saving.",
      },
      {
        q: "Is my file kept on the server?",
        a: "No. It is processed and deleted within the same request. Nothing is stored, and there is no account for it to be attached to.",
      },
      {
        q: "Why is there a 50 MB limit?",
        a: "It stops one job starving the others on a small self-hosted server. Browser-side tools such as Merge and Split have no such cap.",
      },
      {
        q: "Will the text still be selectable afterwards?",
        a: "Yes. Compression targets images and redundant objects, not the text layer.",
      },
    ],
  },

  "pdf-to-jpg": {
    title: "PDF to JPG: Convert PDF Pages to Images",
    h1: "Convert PDF to JPG",
    howTo: "How to convert a PDF to JPG",
    intro: [
      "PDF to JPG works two ways. Page mode renders each page as a JPG at the quality you choose. Extract mode pulls out the images already embedded in the document, at their original resolution.",
      "Page mode runs in your browser with pdf.js and uploads nothing. Extract mode needs server tooling, so those files are sent, processed and deleted in the same request.",
    ],
    steps: [
      {
        title: "Add a PDF",
        body: "Drop in one file or several.",
      },
      {
        title: "Choose pages or embedded images",
        body: "Page mode gives you one JPG per page. Extract mode returns the embedded images, however many the document holds.",
      },
      {
        title: "Download the images",
        body: "A single image downloads on its own. Several arrive together as a zip.",
      },
    ],
    faqs: [
      {
        q: "What is the difference between the two modes?",
        a: "Page mode paints the whole page, text and vector graphics included, into a new JPG. Extract mode returns only the bitmap images the PDF already contains, untouched.",
      },
      {
        q: "Which mode uploads my file?",
        a: "Only extract mode. Page mode renders in your browser and never uploads anything.",
      },
      {
        q: "Can I control the image quality?",
        a: "Yes, in page mode. Higher quality means a larger JPG and a sharper render.",
      },
      {
        q: "Why did extract mode return nothing?",
        a: "The PDF has no embedded bitmap images. A document built from text and vector drawings has none to pull out, so use page mode instead.",
      },
    ],
  },

  "pdf-to-word": {
    title: "PDF to Word: Convert PDF to Editable DOCX",
    h1: "Convert PDF to Word",
    howTo: "How to convert a PDF to Word",
    intro: [
      "PDF to Word rebuilds a PDF as an editable Word document. Paragraphs stay paragraphs, tables stay tables and images keep their place, so you can edit the result rather than retype it.",
      "Conversion runs on the server, where the file is processed and deleted within the same request. Files are capped at 50 MB each.",
    ],
    steps: [
      {
        title: "Add your PDFs",
        body: "Drop in one file or several, up to 50 MB each.",
      },
      {
        title: "Choose whether to use OCR",
        body: "A PDF you can select text in converts without OCR. A scan has no text to read, so turn OCR on and the words are recognised first.",
      },
      {
        title: "Convert and download",
        body: "The .docx downloads as soon as the job finishes and opens in Word, Google Docs or LibreOffice.",
      },
    ],
    faqs: [
      {
        q: "Will the layout survive the conversion?",
        a: "Mostly. Paragraphs, headings, tables and images are rebuilt as real Word content. A heavily designed page with unusual columns or overlapping artwork will come out approximately, not exactly.",
      },
      {
        q: "My PDF is a scan and the Word file came out empty. Why?",
        a: "A scanned page is a picture, with no text to convert. Turn OCR on and the page is read first, so the Word document contains editable words instead of an image.",
      },
      {
        q: "Can I edit the result?",
        a: "Yes. The output is a normal .docx, so text, tables and styles can all be changed like any other Word document.",
      },
      {
        q: "Is my document kept on the server?",
        a: "No. It is converted and deleted within the same request. There is no account and nothing is stored.",
      },
    ],
  },

  "pdf-to-markdown": {
    title: "PDF to Markdown: Convert a PDF to Clean .md",
    h1: "Convert PDF to Markdown",
    howTo: "How to convert a PDF to Markdown",
    intro: [
      "PDF to Markdown turns a document into clean Markdown, keeping the headings, lists and tables it already had. It is the quickest way to get a PDF into notes, a wiki, a static site or a prompt.",
      "Pages that are scans have no text to read, so those are recognised with OCR first and folded into the same file. The result downloads as a single .md.",
    ],
    steps: [
      {
        title: "Add a PDF",
        body: "Drop in one file or several, up to 50 MB each.",
      },
      {
        title: "Leave OCR on for scans",
        body: "Pages with real text are converted directly. Pages that are images are read with OCR, so a mixed document comes back complete.",
      },
      {
        title: "Download the Markdown",
        body: "One file downloads as .md. Several arrive together as a zip.",
      },
    ],
    faqs: [
      {
        q: "What does the Markdown keep?",
        a: "Headings, paragraphs, lists and tables are carried across as Markdown. Visual styling such as fonts, colours and exact spacing is not, which is the point of Markdown.",
      },
      {
        q: "Does it work on scanned PDFs?",
        a: "Yes. A page with no text layer is read with OCR and its text is folded into the document in the right place. Recognised pages come back as plain paragraphs, because a scan has no structure to recover.",
      },
      {
        q: "Why would I want Markdown instead of Word?",
        a: "Markdown is plain text, so it goes straight into a repository, a note-taking app, a static site generator or a language model without carrying formatting baggage.",
      },
      {
        q: "Is my file uploaded?",
        a: "Yes, this tool needs the server. The file is converted and deleted within the same request, and nothing is retained.",
      },
    ],
  },

  ocr: {
    title: "OCR PDF: Make a Scanned PDF Searchable",
    h1: "OCR a scanned PDF",
    howTo: "How to OCR a scanned PDF",
    intro: [
      "OCR runs optical character recognition over a scanned PDF and adds an invisible text layer behind the image. The page still looks exactly the same, but the words can now be searched, selected and copied.",
      "Recognition uses Tesseract on the server, so the file is uploaded, processed and deleted within the same request.",
    ],
    steps: [
      {
        title: "Add a scanned PDF",
        body: "Drop in the file, up to 50 MB. The pages OCR helps are the ones that are images with no text layer.",
      },
      {
        title: "Choose a language",
        body: "Pick the language of the document, so recognition knows what it is reading.",
      },
      {
        title: "Apply OCR and download",
        body: "The result is the same document with a searchable text layer added behind the image.",
      },
    ],
    faqs: [
      {
        q: "What does OCR actually change in the file?",
        a: "It adds a hidden text layer aligned with the words in the image. The visible page is unchanged.",
      },
      {
        q: "Which languages can I use?",
        a: "Fourteen are installed today: Arabic, Chinese (Simplified), Dutch, English, French, German, Hindi, Italian, Japanese, Portuguese, Russian, Spanish, Swedish and Urdu. You can combine up to three on one document. The list is read from the server, so more can be added without a change to this page.",
      },
      {
        q: "My PDF already has selectable text. Do I need OCR?",
        a: "No. If you can already select the text, there is nothing for OCR to add.",
      },
      {
        q: "How accurate is it?",
        a: "Clean, straight, high-resolution scans read very well. Low-resolution, skewed or handwritten pages are much less reliable.",
      },
    ],
  },

  protect: {
    title: "Password Protect a PDF with Encryption",
    h1: "Password protect a PDF",
    howTo: "How to password protect a PDF",
    intro: [
      "Protect PDF encrypts a document so it cannot be opened without the password you set. Anyone who opens it afterwards is prompted before a single page is shown.",
      "Encryption is done with qpdf on the server. The file and the password are used for that one request and then discarded, and the password reaches qpdf through a file rather than the command line, so it never appears in the process list.",
    ],
    steps: [
      {
        title: "Add your PDFs",
        body: "Drop in one file or several, up to 50 MB each.",
      },
      {
        title: "Set a password",
        body: "Type it twice, so a typo cannot lock you out of your own document.",
      },
      {
        title: "Protect and download",
        body: "The encrypted file downloads as soon as the job finishes.",
      },
    ],
    faqs: [
      {
        q: "What happens if I forget the password?",
        a: "Nothing can be done. Neither the password nor the file is kept, so there is no copy to recover and no reset. Store it somewhere safe before you close the tab.",
      },
      {
        q: "Do you store the password?",
        a: "No. It is used for the single request that encrypts your file and then discarded.",
      },
      {
        q: "What encryption is used?",
        a: "AES-256, via qpdf. Current PDF readers all support it.",
      },
      {
        q: "Can I remove the password later?",
        a: "Yes, with Unlock PDF, as long as you still know it.",
      },
    ],
  },

  unlock: {
    title: "Unlock PDF: Remove a Password You Know",
    h1: "Unlock a PDF",
    howTo: "How to unlock a PDF",
    intro: [
      "Unlock PDF removes the password from a document you already have the right to open, so it stops prompting every time. You supply the password and the tool writes out a copy without the encryption.",
      "Decryption uses qpdf on the server. The file and the password are used for one request and then discarded.",
    ],
    steps: [
      {
        title: "Add the protected PDF",
        body: "Drop in the file. Encrypted files are recognised and marked as soon as they are read.",
      },
      {
        title: "Enter the password",
        body: "Type the password that currently opens the document.",
      },
      {
        title: "Unlock and download",
        body: "The copy that downloads opens with no prompt.",
      },
    ],
    faqs: [
      {
        q: "Can this crack a password I do not know?",
        a: "No. This tool removes a password you can already supply. It does not guess one, brute-force one or bypass one.",
      },
      {
        q: "What if the PDF only restricts printing and copying?",
        a: "A document with an owner password opens without a prompt but still refuses to save in some tools. Running it through Unlock clears that restriction.",
      },
      {
        q: "Is the password stored?",
        a: "No. It is used for the single request and then discarded.",
      },
      {
        q: "Why does each file need its own request?",
        a: "Each PDF has its own password, so each one is unlocked separately.",
      },
    ],
  },
};
