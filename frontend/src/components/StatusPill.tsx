interface Props {
  status: string;
}

export function StatusPill({ status }: Props) {
  return <span className={`pill pill-${status}`}>{status.replace(/_/g, ' ')}</span>;
}
