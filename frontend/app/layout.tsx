import { Public_Sans } from 'next/font/google';
import localFont from 'next/font/local';
import { cn } from '@/lib/utils';
import '@/styles/globals.css';
import ClientLayout from './ClientLayout'; // client-side dynamic stuff

const publicSans = Public_Sans({ variable: '--font-public-sans', subsets: ['latin'] });
const commitMono = localFont({
  display: 'swap',
  variable: '--font-commit-mono',
  src: [
    { path: '../fonts/CommitMono-400-Regular.otf', weight: '400', style: 'normal' },
    { path: '../fonts/CommitMono-700-Regular.otf', weight: '700', style: 'normal' },
    { path: '../fonts/CommitMono-400-Italic.otf', weight: '400', style: 'italic' },
    { path: '../fonts/CommitMono-700-Italic.otf', weight: '700', style: 'italic' },
  ],
});

interface RootLayoutProps {
  children: React.ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={cn(publicSans.variable, commitMono.variable, 'scroll-smooth font-sans antialiased')}
    >
      <head>
        {/* Add deterministic meta, fonts, etc. */}
        <title>My App</title>
        <meta name="description" content="My App Description" />
      </head>
      <body className="overflow-x-hidden">
        {/* Move all dynamic scripts/components to client component */}
        <ClientLayout>{children}</ClientLayout>
      </body>
    </html>
  );
}
