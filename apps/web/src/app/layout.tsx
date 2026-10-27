import "./globals.css";
export const metadata = {title: "SomaLoom | Educational Publishing Studio", description: "Research, prepare and publish curriculum-aligned educational materials."};
export default function RootLayout({children}: {children: React.ReactNode}) { return <html lang="en"><body>{children}</body></html>; }
