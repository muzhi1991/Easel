import { Children } from 'react';
import type { ReactNode } from 'react';

const LABELS = ['顺序', '供应商', '类型', '模型', 'Base URL', 'API Key', '角色', '连接状态', '操作'];

/** Preserve the desktop grid; expose field labels when rows become mobile cards. */
export default function ProviderRow({ children }: { children: ReactNode }) {
  return <div className="prow">
    {Children.toArray(children).map((child, index) => <div className={`provider-cell provider-cell-${index}`} key={index}>
      <span className="mobile-field-label">{LABELS[index]}</span>
      {child}
    </div>)}
  </div>;
}
