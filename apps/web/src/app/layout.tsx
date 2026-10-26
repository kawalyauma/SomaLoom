import "./globals.css";
export const metadata = {title: "SomaLoom", description: "Educational content intelligence"};
export default function RootLayout({children}: {children: React.ReactNode}) {
  return <html lang="en"><body>{children}</body></html>;
}
