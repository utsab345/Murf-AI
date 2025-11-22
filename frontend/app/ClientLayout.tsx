'use client';

import { useEffect, useState } from 'react';
import { ApplyThemeScript, ThemeToggle } from '@/components/app/theme-toggle';
import { getAppConfig, getStyles } from '@/lib/utils';

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const [styles, setStyles] = useState('');
  const [pageTitle, setPageTitle] = useState('My App');
  const [pageDescription, setPageDescription] = useState('');

  useEffect(() => {
    async function load() {
      const appConfig = await getAppConfig();
      setPageTitle(appConfig.pageTitle || 'My App');
      setPageDescription(appConfig.pageDescription || '');
      setStyles(getStyles(appConfig) || '');
    }
    load();
  }, []);

  return (
    <>
      {styles && <style>{styles}</style>}
      <ApplyThemeScript />
      {children}
      <div className="group fixed bottom-0 left-1/2 z-50 mb-2 -translate-x-1/2">
        <ThemeToggle className="translate-y-20 transition-transform delay-150 duration-300 group-hover:translate-y-0" />
      </div>
    </>
  );
}
